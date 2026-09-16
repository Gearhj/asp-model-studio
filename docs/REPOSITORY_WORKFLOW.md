# Private repository publication and recovery

Repository: https://github.com/Gearhj/asp-model-studio (private, verified 2026-09-16).

## Current development is not the deployed owner

- Original current development: `codex/mlb-starter-duration-source-intake-v1`, commit `0c786297534c1ffc9892fbcd199d7d7af5ec8bae`.
- Actual MLB Windows S4U owner: `ASP MLB V18 Research Publisher`, deployed `77d39e1ae08e05be82e19bdb0bab21999fba1d3b`.
- The deployment pointer and its 872 code-file hashes were verified without starting, stopping or reinstalling the owner. The development working tree and real Git index were preserved.
- `main` and the default remote branch retain their historical meanings. A branch named research, champion, candidate, or checkpoint does not confer production or wagering authority.

See `repository-publication/2026-09-16/` for exact ref mapping, review, source-checkpoint provenance and remaining gaps. Some original later histories cannot be pushed intact: three ancestor model blobs exceed GitHub's 100 MiB limit. A tip deletion would not remove them from ancestry. The current development branch also contains prospective-only restricted source objects. No existing history was rewritten.

## Commit and push procedure

1. Read AGENTS.md and the actual clock. Record branch, full HEAD, deployed pointers, `git status --short`, other worktrees and relevant owners. Do not assume a stale handoff is current.
2. Confirm the exact remote and authenticated identity. Verify repository visibility remains private. Fetch without merging, rebasing, pruning or resetting.
3. Review **all newly reachable history**, not just the latest diff. Inventory blob paths/types/sizes before examining content. Do not open sealed outcomes for a publication scan. Do not print credentials or copy `.env.local`, runtime databases, tokens, private-source payloads or raw exchange contents into Git.
4. Review source/data permissions. A private repository is not a blanket exception to a source-use restriction. Model files and research tables need their own artifact/storage decision. Ignore rules do not remove already-tracked history.
5. Stage only explicit reviewed paths (`git add -- path1 path2`). Inspect `git diff --cached --stat` and `git diff --cached --check`; inspect the actual staged diff without exposing secret values. Never use indiscriminate `git add .`/`-A` for this repository.
6. Commit source implementation and retained admissible evidence separately. Preserve unfinished work on an explicitly named `codex/checkpoint/...` branch, marked unvalidated/unpromoted. Do not include moving runtime pointers merely to make status clean.
7. For a normal eligible branch, run a non-force dry run with an explicit refspec, then push that same refspec. Preserve divergent remote work with a new branch. Do not use `--force`, `--mirror`, history rewriting, branch deletion or silent changes to the remote default.
8. Verify full remote SHAs using `git ls-remote`, then verify them in a fresh clone. Verify source checkpoints against their per-file Git object IDs and deployment manifests. A source checkpoint is not the original commit or its full omitted history.
9. Leave deployment activation to the existing supported owner. A successful Git push is neither a deployment nor an AISP import. Do not restart services or rerun models to prove repository publication.

The dated audit scripts are a reproducible record of this publication, not an unattended general-purpose publisher. A future plan needs a fresh inventory and review; do not replay a stale allowlist after branch changes.

## What a clone does and does not recover

| Category | Coverage / required recovery evidence |
|---|---|
| Reviewed Git branches and source checkpoints | Remote full-ref verification and fresh-clone file verification |
| Withheld original development/deployed history | Still local in Git; three oversized model objects prevent ordinary GitHub refs. Exact source checkpoints do not recover their commit ancestry |
| Fitted models and retained simulation populations | Mixed: some historically tracked, some oversized/ignored/untracked. Need an independently authorized artifact backup, hashes and restore test; a source clone is incomplete |
| Stash | Original stash and its third parent remain local. Contains 525 files / 608,632,778 bytes, mostly test caches plus a workbook and a report. Not discarded or represented as cloud-backed |
| Runtime and deployments | `.runtime/` and `.deployments/` remain local. Runtime databases, locks, scheduled-task definitions, environment and Python dependencies require separate recovery; do not copy stale locks or autoactivate tasks during restore |
| Exchange | `C:\Users\james\asp-model-exchange` is separate from this repo. Forecast packages, raw/normalized sources and consumer receipts need a separate immutable backup and source-permission review |
| Data staging | External source stores, sealed evidence and provider receipts remain governed separately. Quarantine and retention rules survive every backup/restore |
| AISP | Separate repository/database and consumer ownership; this task does not back it up or modify it |

No complete off-machine backup of model artifacts, runtime or exchange was established by this publication. An independently authorized private artifact destination (and explicit permitted handling of restricted source objects) is needed before claiming full recovery. Replacing large historical blobs with LFS pointers would rewrite affected commit identities and was not authorized here.

## Historical material and cleanup

The 36 inherited root ATLAS reports and branding/framework history are retained. Their existence is not a reason to delete or move them. `.env.modeling` and `.env.scheduling` were reviewed as non-secret mode/path configuration, not confused with `.env.local`. Existing fixed local-development/test credentials were recorded without values; no authentication behavior or live secret was changed.

New ignore rules cover explicitly identified test copies, temporary output, protected raw source directories and `model.joblib` files. They leave tracked history and all files on disk intact. No garbage collection, recursive deletion, pruning, reset or branch removal was performed.
