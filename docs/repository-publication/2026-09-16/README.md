# Private GitHub publication and preservation closeout

Verified 2026-09-16. Repository: https://github.com/Gearhj/asp-model-studio . Authenticated identity: Gearhj. Repository visibility is **private**; administrator/push/pull permission verified through the GitHub connector and authenticated native Git operations. The remote default stays `phase7b0-bronze-data-landing`; no branch was relabelled as production.

## Outcome

**59 branches are published and independently cloned: 55 original branches at their exact full commits, plus four explicitly identified source/checkpoint/documentation branches.** Of 67 original local branches, 12 remain local-only because their original history contains three model blobs over GitHub's 100 MiB limit. The original current development branch additionally includes 18 prospective-only restricted source objects. No local or remote tags existed, and none were invented.

The first atomic push updated 54 refs: 53 new branches and a fast-forward of `phase7d3-immutable-evidence-closure` from `50bc1bbcb9897e1c71ae959be5065eac2e75212b` to `fe9fd790b4bb713256763b13fcd319044d35df27`. `phase7b0-bronze-data-landing` stayed at `962a40b19d6a0ee22782a0ec1fff577b25948098`. The second atomic push published four source-preservation branches. A subsequent documentation-only fast-forward retains the final audit; consult its remote ref for the tip.

No force/mirror push, rewrite, reset, merge, rebase, deletion, pruning, garbage collection, service restart, model execution, provider request, production activation or AISP write was performed. Existing GitHub Security Gate configuration can run on a `main` push; it was neither changed nor manually invoked. Publication is not deployment, promotion, or consumer import.

## Original and preserved identities

| Meaning | Exact commit | Remote preservation |
|---|---|---|
| Original current development, `codex/mlb-starter-duration-source-intake-v1` | `0c786297534c1ffc9892fbcd199d7d7af5ec8bae` | Original commit remains local-only; 2,582 selected source/document files preserved separately |
| Development source snapshot | `9a5edbe46e4398e5dffb9ddc5052496b93499486` | `codex/archive/development-source-0c786297` |
| Actual MLB S4U owner deployment | `77d39e1ae08e05be82e19bdb0bab21999fba1d3b` | Original commit remains local-only; all 872 deployed code files preserved separately |
| Deployed code snapshot | `5932310243fe40a31b02ba8dc46383c97d5c97e5` | `codex/archive/mlb-owner-source-77d39e1a` |
| Thirty unfinished source/document files, including the existing transform edit | `34ef33401ba838e6e8740cbc43044b5d8ffb66f5` | `codex/checkpoint/unfinished-source-20260916`; unvalidated and unpromoted |
| Initial publication tooling/documentation/hygiene | `53387e7537b6af7316b31ec2032d8b85acee20d3` | `codex/repository-publication-20260916`; later documentation commit follows |

Source snapshots use a reviewed older safe parent, not the blocked original tip. Their `SOURCE_SNAPSHOT.json` records every included path and Git blob identity, original source identity, and lack of deployment authority. Their trees omit fitted artifacts and runtime data. Older admitted artifacts in the safe parent history are not removed. **A matching source file is not a claim that the omitted original ancestry has been published.**

The deployed owner is `ASP MLB V18 Research Publisher`, from the existing `.runtime/mlb-v18-unattended/deployment.json` pointer. Its `deployment-build.json` physical SHA-256 is `0622b5395072283903669646ab993c80a3ebf3c01e4299132ce086fabca1d3ce`. All 872 deployed file sizes and SHA-256 values matched both the local deployment manifest and blobs retrieved from the independent GitHub clone. No task was started, stopped, reinstalled or replaced.

## Review and cleanup

The original inventory covered 67 branches, no tags, one stash, nine worktrees, 18,252 reachable Git objects and eight preexisting tracked modifications. It recorded 15,403 untracked paths / 4,688,656,051 bytes; this initial count includes one newly created audit script and is not a claim that a live workspace stayed static.

The review inspected 6,468 eligible historical source/text/JSON blobs and commit messages, including original remote ancestry. Thirty-nine credential-pattern findings were classified without recording values: fixed development/test values and URL fixtures already represented in the private remote. An additional 920 source-file checks for snapshots/unfinished changes had no unresolved new signature. This is a bounded pattern/provenance review, not proof that every opaque binary is secret-free. Serialized models were not executed, sealed outcome payloads were not opened, and restricted source objects were classified from identity/path metadata only.

The 36 inherited root ATLAS reports are preserved in place. Tracked `.env.modeling` and `.env.scheduling` contain application-mode/local-path settings, not credential-named configuration; `.env.local` was not opened or published. No live credential was printed or rotated.

Cleanup added ignore rules for identified temporary/test copies, synthetic/dry-run exchange outputs, protected raw source directories and new `model.joblib` files. Ignore rules neither delete files nor remove tracked historical blobs. No historical directory was moved because dependency-safe reorganization was not established. `docs/REPOSITORY_WORKFLOW.md` now documents deliberate staging, full-history review, private-remote verification and backup distinctions.

The real Git index and original HEAD stayed unchanged while commits were constructed using separate indexes. Seven of eight initial dirty-file hashes, including the unfinished transform source, matched the initial capture. The existing NFL owner advanced `outputs/nfl-forward-vintages-v1/CURRENT.json` at 12:41:43Z during the task. It was not restored, staged or overwritten. No claim is made that autonomous runtime evidence was frozen.

## Remaining preservation gaps

| Gap | Exact status / next required action |
|---|---|
| Twelve original branch histories | Listed individually with full SHAs in `BRANCH_MAPPING.csv`. Local refs and objects are unchanged. Current development and deployed original commits fail lookup in the fresh clone, as explicitly recorded. |
| Three oversized historical model blobs | `2b26617263fda09f34b7ee58293a26c211f584ae` — 114,762,617 bytes; `69d503a511007a6282a7cdde0cc5efbe6e6ac70e` — 131,976,505 bytes; `d9fcba88a997b6228a28226b36d44ba1a00a5751` — 114,712,969 bytes. Full paths are in `inventory-summary.json`. GitHub ordinary Git rejects files over 100 MiB. A later deletion commit cannot repair ancestor blobs. LFS migration would rewrite commit identities, prohibited for this task. |
| Eighteen restricted source blobs | Under `outputs/mlb-starter-duration-paired-research-v1/intake/prospective-only-source-quarantine/objects/sha256/`. Not opened or uploaded by this task. A private repo alone does not authorize wider source use or backup dissemination. |
| Source snapshot omissions | `SOURCE_CHECKPOINT_EXCLUSIONS.json` lists 6,953 omitted development-tree paths. Many are legitimate model/evidence assets rather than secrets; an allowlisted source snapshot is deliberately incomplete. Existing safe historical branch coverage is separate. |
| Stash | `stash@{0}` = `6f5c0580df6f41f73e7ec413a3840186ca39029f`; third parent `b61e01d3de39e568a7f490448b8ea69b3fecff2f` contains 525 files / 608,632,778 bytes, mostly temporary test assets plus `ASP_MLB_Feature_Treatment_Specification.xlsx` and `docs/PHASE_7D3_CODEX_FINAL_SILVER_READINESS_REPORT.md`. It was not dropped, applied, or published. |
| Untracked evidence and other worktrees | Initial local inventory retained under `.runtime/github-publication-20260916-v1/`. Thirty unfinished source/docs were checkpointed; remaining generated/raw/binary evidence is not newly claimed as cloud-backed. The spatial worktree's untracked NFL declaration remains local and untouched. |
| Fitted models, simulation populations, source stores | Some earlier permitted artifacts are in safe histories; oversized, ignored and untracked assets lack a verified complete off-machine backup. Require a permission-reviewed artifact backup with manifest and restore test. |
| Runtime/deployment/environment | Code hashes preserved; live databases, scheduler definitions, dependencies, secrets, locks and all runtime receipts are not reconstructed by a clone. Need a separate secure recovery procedure that does not replay stale locks or automatically start owners. |
| Exchange and AISP | `C:\Users\james\asp-model-exchange` has separate packages/source permissions/consumer receipts. Its complete backup was not established. AISP repository and database were not modified or backed up here. |

GitHub limit reference: https://docs.github.com/en/repositories/working-with-files/managing-large-files/about-large-files-on-github .

The smallest unresolved preservation decision is an **approved private artifact-backup destination and permitted handling of the restricted source objects**, so intact Git history, large fitted assets and governed evidence can be backed up without rewriting their identities. No destination, paid service, retention exception or protected-data upload was assumed. Rewriting original history is a different decision and remains outside this task.

## Focused verification and reproducible commands

`fresh-clone-verification.json` records 59 exact remote refs, 59 exact clone refs, no tags, successful connectivity checking, the original-history gaps, matching source manifests and all 872 deployed physical hashes. The clone is under `.runtime/github-publication-20260916-v1/fresh-clone`, fetched from HTTPS GitHub without local object alternates, shallow history, partial filtering or a working-tree checkout.

From this preserved workspace, after a normal fetch in the audit clone:

```powershell
git -C .runtime/github-publication-20260916-v1/fresh-clone fetch origin --no-tags --no-recurse-submodules
.venv\Scripts\python.exe scripts/verify_repository_publication.py
git ls-remote --heads --tags origin
```

The dated scripts require the retained local audit plans; they are not an unattended generic publisher. Do not blindly rerun the original push/create scripts after branches advance. The documentation commit may move only by an ordinary reviewed fast-forward; the final live verification receipt remains in the local audit directory and includes its exact tip.

Publication/review receipts, the full branch mapping and source-checkpoint exclusions accompany this report. Future source/commit/push and recovery instructions are in `docs/REPOSITORY_WORKFLOW.md`. No broad model or application test suite was run to justify repository publication.
