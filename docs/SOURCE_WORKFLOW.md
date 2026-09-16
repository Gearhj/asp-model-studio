# Source-only development workflow

Use **C:\Users\james\asp-model-studio-source** for subsequent source coding sessions. The initial working branch is **codex/source-development-v1** in the existing private repository https://github.com/Gearhj/asp-model-studio . This independent clone has its own Git directory and no object alternates, worktree dependency or runtime link to the original repository.

Its exact base is `codex/archive/development-source-0c786297`, commit `9a5edbe46e4398e5dffb9ddc5052496b93499486`. This is a source snapshot of original development `0c786297534c1ffc9892fbcd199d7d7af5ec8bae`, not that original commit's full history. The retained root `SOURCE_SNAPSHOT.json` describes the **archive base**, not every later documentation/code commit. Do not regenerate or reinterpret that provenance manifest as a current production manifest.

The coordinator's completed 59-branch publication verification is accepted. This workflow does not repeat it. The earlier closeout remains available at https://github.com/Gearhj/asp-model-studio/blob/63e7bddada991f3754bc721df8c62ae60a869379/docs/repository-publication/2026-09-16/README.md .

## Starting a coding session

```powershell
Set-Location C:\Users\james\asp-model-studio-source
git status --short
git branch --show-current
git rev-parse HEAD
git fetch origin --no-tags --no-recurse-submodules
```

Read AGENTS.md and this file. Confirm the intended task scope, inspect any local edits, and coordinate branch ownership before changing files. This checkout's single-branch fetch configuration also tracks `codex/source-development-v1` after its initial push. Future task branches should be based on its reviewed source line, for example `git switch -c codex/<task-name> codex/source-development-v1` when the checkout is clean and the base has been reviewed. Do not switch branches through unrelated dirty work.

Stage explicit source/document paths only. Inspect the actual staged changes and newly introduced files. Do not use `git add .` or `git add -A` here. Check credentials, source permissions, large generated files and runtime references before committing. Use normal commands:

```powershell
git add -- <reviewed-paths>
git diff --cached --stat
git diff --cached --check
git commit -m "<describe the reviewed source change>"
git push --dry-run origin HEAD:refs/heads/<your-branch>
git push -u origin HEAD:refs/heads/<your-branch>
# For a new task branch, add its name to this single-branch clone's fetch list once:
git remote set-branches --add origin <your-branch>
git ls-remote --heads origin refs/heads/<your-branch>
```

Match the full remote SHA to local HEAD. If a remote advanced, fetch and inspect it; never force a push or overwrite another session's work. Do not merge the blocked original development/research histories into this source line. They still contain oversized and restricted ancestor objects. Do not add the original repository as an alternate object store, mirror its refs, or migrate its history to LFS as an incidental cleanup step.

## Subsequent and unfinished changes

All nine previously registered original worktrees had unchanged HEADs when this workflow began. The eight non-root worktrees had no tracked edits. The root retained its prior dirty work and the spatial worktree's previously recorded untracked NFL declaration remains outside this checkout. Do not apply or discard their work from this clone.

The 30 reviewed source/document files in `codex/checkpoint/unfinished-source-20260916` (`34ef33401ba838e6e8740cbc43044b5d8ffb66f5`) still matched the captured physical hashes. They remain **unfinished and unvalidated** and were **not imported into the active source branch**. This includes the existing edit to `server/sports_current_statcast/mlb_v18_prospective_transform.py`. Security review and byte preservation do not establish functional validation. No unfinished model code was transferred.

Completed publication tooling and reports are preserved on `codex/repository-publication-20260916` at `63e7bddada991f3754bc721df8c62ae60a869379`. Its already-reviewed ignore cleanup was transferred by path. The archival publication scripts were not installed as ongoing publishers. No subsequent model-source commit was found: the original root remains at `0c786297534c1ffc9892fbcd199d7d7af5ec8bae`.

To resume an unfinished item, first read the source change ledger and its original task/evidence. Fetch only the required safe checkpoint ref into this clone, inspect its selected file diff against the archive base, and apply only the reviewed source delta on a task branch. Do not merge the entire checkpoint or treat its 30 files as a tested release. Carry the unvalidated status until the task's focused checks support a stronger claim. New changes discovered later require a fresh delta review; do not copy a whole live working tree.

The workflow-verification commit changes documentation/ignore rules only, using ordinary `git add` and `git commit` and an ordinary non-force push. A preceding source-restoration commit restores four inherited application TypeScript modules under `src/data/` and five static image/icon assets that the snapshot allowlist had omitted. Every restored blob is identical in original development and the already published safe parent `fe9fd790b4bb713256763b13fcd319044d35df27`. These are application resources, not model inputs or a new model change. Its full identity is available from this branch's Git history and the local completion receipt. No model rerun or broad test suite is required to prove that Git workflow.

## What remains external

This is **not a reconstructed running system**. Current serialized model weights, fitted preprocessing, residual donors, saved joint simulation populations, live registry records, source datasets and runtime databases are not included in the source working tree. Historical artifacts in the older safe Git ancestry do not establish recovery of the current deployment.

| Required category | Existing location / handling |
|---|---|
| MLB V18 learned PA estimators and fitted treatment, runtime component/template artifacts, current pregame source bindings and retained draws | Original `outputs/`, `server/artifacts/`, `.runtime/asp-model-studio/`, and external staging/exchange as selected by the governed owner. Recover the exact artifact and input hashes; a code file or similarly named model is insufficient. |
| NFL M1 weights/preprocessing, Foundation/current-season feature evidence and forecast populations | Original model registry/output/runtime plus `C:\Users\james\asp-data-staging\nfl` and exchange. The separate play-level research models remain separate. |
| NBA Ridge/Elo and assessed joint-distribution fitted/residual artifacts; CFB Gen 1 fitted artifacts and feature/source receipts | Original sport output/registry directories and exchange. Research status and source licensing restrictions remain attached. |
| Raw, normalized and historical source evidence | `C:\Users\james\asp-data-staging`, original `outputs/` private source roots, and exchange datasets. Source files are not automatically licensed for copying merely because the code is available. |
| Application persistence, security, dataset library, registry and owner state | Original `.runtime/asp-model-studio`, `server/artifacts`, `server/data`, and `.runtime/mlb-v18-unattended`. Live databases need an application-consistent backup; a metadata walk is not one. |
| Existing deployment | Original `.deployments/mlb-v18-unattended/77d39e1ae08e05be82e19bdb0bab21999fba1d3b`; its `.runtime` and `outputs` junctions point back into the original repository. No junctions are recreated here. |
| Secrets, local configuration and environment | Original ignored `.env.local`/environment and secured runtime configuration; none copied. Tracked `.env.modeling`/`.env.scheduling` are mode/path examples, not complete live configuration. Create only explicitly authorized isolated configuration when a later task needs it. |
| Dependencies and machine ownership | Reinstall from package/requirements definitions into a separate environment when authorized. Original Python environment, Windows task/S4U identity, credentials, locks and service ports are not recreated by cloning. |
| Immutable producer/consumer evidence | `C:\Users\james\asp-model-exchange` is separate and remains under its existing owners. Publication, AISP import, decision and settlement identities are distinct. No AISP repository/database is modified here. |

The new ignore guardrails prevent routine staging of new runtime, fitted, data and output payloads. Already tracked source and historical report files remain tracked. Small deterministic test fixtures may be admitted later only by explicit review; avoid using force-add as a shortcut around evidence permissions.

## Production remains separate

The original workspace, its nine worktrees, running services and deployments remain in place. Do not run the original startup/publisher/install scripts from this clone merely to verify development: their default ports and owner assumptions can conflict with running services. No scheduler, publisher, service, source collector or task is activated here. Production deployment requires a separate explicit request, exact artifact/environment bindings and the existing owner's governed activation path.

MLB quarantine and sealed-evidence rules in AGENTS.md are unchanged. A source-only branch conveys no evaluation, promotion, wagering, provider-use or AISP-write authority.

## Non-Git recovery coverage

See `source-workflow-20260916/RECOVERY_SIZE_COVERAGE.json` and `BACKUP_DESTINATIONS.json`. The file-level metadata inventory remains local at `C:\Users\james\asp-model-studio\.runtime\source-workflow-20260916-v1\RECOVERY_FILE_METADATA.jsonl`; its SHA-256 is recorded in the summary. The inventory records paths, lengths, modification times and filesystem attributes; it does not open/hash protected payloads or upload files.

The inventory counted **71,702 files / 42,296,516,316 logical bytes**, including the original Git store and pre-existing backup copies. It is not a compressed/deduplicated backup estimate. **435 access errors** make it a lower bound: 56 in outputs, 116 in runtime, five in staging, and 258 in exchange. Eighteen links/junctions were recorded without traversal. The verification clone and inventory's own directory were excluded; dependency installations and AISP's repository/database were outside scope.

The existing private OneDrive destination is `C:\Users\james\OneDrive\ASP-Platform-Backups`. Its September 5 manifest states that authorization covered **only two exact named bundle files**. The Model Studio bundle is 213,810,080 bytes and represented required HEAD `bff19a8a657bc96dea0469fad481acdcb4234386`, not today's complete history. Its prior SHA is recorded as historical evidence, not reverified by opening the bundle. The manifest still labels cloud sync `NOT_VERIFIED`. Two older missing loose documents are now represented in the locally preserved stash; that does not prove they reached OneDrive.

The configured Model Studio dataset-backup root is local `.runtime/asp-model-studio/backups/datasets`; it existed but contained no inventoried files at inspection time. The legacy `%LOCALAPPDATA%/ATLAS/dataset-library-backups` contains 60 small files (53,160 bytes), not a complete Model Studio recovery set. GitHub is approved for reviewed source; it is not a replacement destination for all current raw/model/runtime payloads.

**Remaining permission/coverage requirements:** authorize a new, explicitly scoped Model Studio recovery set in the existing private OneDrive destination (or name another approved destination), with retention/encryption handling appropriate for credentials and restricted data. The old two-file approval is not a blanket authorization for a new Git bundle or current source/model/runtime/exchange contents. Keep sealed/prospective-only/licensed payloads excluded unless their exact backup handling is separately permitted; do not request or imply an evaluation exception. A metadata-only list/read grant from the existing owner is also needed for the 435 denied paths to complete size coverage. No filesystem permission was changed or bypassed. Finally, obtain actual remote-sync and isolated restore evidence before calling any new recovery set complete.
