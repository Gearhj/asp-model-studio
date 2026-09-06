# ASP Model Studio tenant repair — controlled integration runbook

This runbook is NOT executed here. It is the exact plan to integrate the
independently verified repair. Verdict: GO_FOR_INTEGRATION.

## Lineage (verified)

One linear chain — no divergence:

```
main 924db29  ->  ... ->  primary 33cd85f (codex/mlb-governed-prior-engine-v1)
             ->  ... ->  wave2 bff19a8 (codex/mlb-player-prior-wave2)
             ->  8 commits ->  repair 9f02e683 (codex/model-studio-tenant-workflow-repair-v1)
```

- `main..repair` = 215 commits, linear (main is an ancestor of repair).
- `primary(33cd85f)..repair` = 23 commits, **0 divergent commits** — the primary
  checkout is a clean earlier point on the same line.
- `wave2(bff19a8)..repair` = 8 commits.
- A **clean fast-forward is possible** onto main, the primary branch, or wave2.

## Steps

1. **Reverify the repair HEAD**: `git rev-parse codex/model-studio-tenant-workflow-repair-v1` == `9f02e6835f578b13d0429d0a7442b3634048f8f2`.
2. **Reverify main and the primary branch**: main == `924db29511f93909f9d785855bfa056775443690`; primary checkout branch `codex/mlb-governed-prior-engine-v1` == `33cd85f…` and clean.
3. **Fresh backups** (before any ref move):
   - Git: `git bundle create asp-model-studio-preintegration-<date>.bundle --all`; record SHA-256.
   - Canonical runtime prior objects: copy `.runtime/asp-model-studio/stage3-player-prior-authorities-v2` off-box; record its 9 object SHAs.
   - Model Studio SQLite: back up `.runtime/asp-model-studio/persistence/asp_model_studio.db` via the SQLite backup API (`sqlite3.Connection.backup`), not a file copy (WAL).
4. **Verify the SQLite backup**: open the backup read-only and run `PRAGMA integrity_check` == ok; compare table counts to the live DB.
5. **Preserve the Wave 2 source worktree** (`.tmp/asp-player-prior-wave2`) until post-integration verification passes; do not prune.
6. **Choose the integration target**: fast-forward the active development branch
   (`codex/mlb-governed-prior-engine-v1`, or `main`) to `9f02e683`. Because the
   distance is linear with zero divergence, this is a non-destructive
   fast-forward: `git checkout <target> && git merge --ff-only 9f02e683`.
7. **Integrate without losing history**: `--ff-only` keeps the complete Wave 2 and
   repair commit history. Do not squash, rebase, or reset.
8. **Restart primary services only after tests pass**: run the repair's tenant +
   Stage 3 suites against a disposable copy first; then restart backend (uvicorn
   :8101) and frontend (vite :5274) via scripts/start-asp-model-studio.ps1 -Start.
9. **Verify the canonical prior resolver on the real primary runtime**: confirm the
   asp-mtlozhdx pointer resolves the fit bundle (authorityId 9d9cfaf3) from the
   primary `.runtime` with all 9 objects content-addressed, and that resolution
   never touches `.tmp/asp-player-prior-wave2`.
10. **Verify login and project access**: a normal user logs in; a foreign user is
    denied (403) on another user's project and its ACL.
11. **Verify pilot and challenger**: pilot `asp-mtddc6pw` and deliberate challenger
    `asp-mtlozhdx` both open; challenger shows dev 683,662, final OOT 14,067 locked.
12. **Verify all seven challenger downstream pages** render with truthful empty
    states (no pilot candidates/receipts/finalist/champion), treatment DRAFT,
    adoption blocked, and zero auto-created model jobs.
13. **Verify zero OOT access**: final-OOT stays KEY_ONLY_UNMATERIALIZED_LOCKED_UNOPENED (payloadRowsRead 0).
14. **Reconcile protected DB tables** against the pre-integration snapshot
    (projects, policy versions, feature sets, run_records, audit_log): only
    expected, attributable rows changed.
15. **Rollback conditions and steps**: if canonical resolution fails, any tenant
    isolation probe regresses (foreign 403 not returned), a pilot artifact leaks
    into the challenger, or OOT payloadRowsRead != 0 — restore the branch ref
    (`git update-ref refs/heads/<target> <prior-sha>`), restore the SQLite backup,
    restore the canonical prior objects from step 3, and re-verify integrity.
16. **Keep semantic/rivalry treatment closure as a separate later task** (out of
    scope for this integration).
17. **Do not fit a challenger during integration.**
