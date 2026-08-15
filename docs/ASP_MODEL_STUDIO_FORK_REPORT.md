# ASP Model Studio Fork Report

## Executive Result

`FORK_COMPLETE_WITH_VERIFICATION_LIMITATIONS`

The independent ASP Model Studio baseline was created successfully at `C:\Users\james\asp-model-studio`. It preserves full ATLAS history through the fork point, captures the approved safe working-tree state in a dedicated snapshot commit, has its own Git object database and dependencies, has no remote, and uses a fail-closed target-local runtime launcher. Financial-services ATLAS remained exactly unchanged.

The limitations are inherited or environmental: the root Python requirement set cannot resolve as pinned, the host has Node 24 rather than CI's Node 20, three experiment canonical-identity assertions are inconsistent with the captured ATLAS implementation, and live/E2E startup was intentionally outside this fork run. No fork-copy or remaining runtime-isolation defect was found.

## Source ATLAS Baseline

- Path: `C:\Users\james\ds-workflow-starter`
- Branch: `codex/phase2a-canonical-lineage`
- HEAD: `e13ac139ec1d684935f50272f2c9cd3ef693ad9d`
- Upstream: `origin/codex/phase2a-canonical-lineage`
- Status: 143 modified, 1 deleted, 0 staged, 33 Git-visible untracked, 177 porcelain entries
- Status fingerprint: `53feb055ccaaf181aa76c222d02cae02de05093a76920c7bfbbe3bacc9564d6c`
- Index fingerprint: `4ed8f33a26ece67b4b1b19066b6001134ddbc1a717186aedcf65934d773f926a`
- Tracked files: 2,277
- Git-visible paths: 2,310
- Git-visible bytes: 567,525,939
- Baseline manifest SHA-256: `fb2f949cb6b376c37495b4b6de92e82fc1a76fdde2a25415e012676695d37b01`

The observed live baseline matched the reference branch, HEAD, counts, and status fingerprint supplied for this operation. The content manifest records path, tracking state, type, existence, size, SHA-256, Git mode, filesystem attributes, and line-ending attributes for every Git-visible path.

## Source Changes Captured

- Modified tracked source paths present at baseline: 143
- Safe modified tracked paths captured: 127
- Deleted tracked paths captured: 1 (`test-results/e2e/artifacts/.last-run.json`)
- Staged source paths: 0
- Safe untracked paths included: 17
- Included untracked composition: one implementation report, six application modules, and ten test files

The exact safe-untracked list and hashes are in `docs/fork-evidence/included-untracked-inventory.json`. Four initially uncertain files were resolved by direct import and test references; the final ambiguous count is zero.

## Excluded Source Content

- Runtime/generated Git-visible untracked paths: 16, all generated files under `server/artifacts`
- Modified tracked runtime/test-output deltas excluded: 16; the target retained their inherited HEAD versions
- Secret/local configuration copied: none
- Ignored dependencies/caches copied: none (`.venv`, `node_modules`, `dist`, `.tmp`, `.runtime`, bytecode, test caches)
- Local databases, SQLite sidecars, logs, and local artifacts copied: none
- Ambiguous Git-visible paths: 0
- Inaccessible generated cache directories excluded without traversal: 20

The ignored source `.env.local` was not copied or read. The inherited tracked `.env.modeling` and `.env.scheduling` files contain only credential-free mode keys. Historical artifacts already committed in ATLAS history remain inherited; no source-local runtime/artifact delta was added to the snapshot.

## Independent Git Creation

- Clone method: local `git clone --no-hardlinks`
- Source HEAD at clone: exact baseline HEAD
- `.git`: independent directory with its own index and object database
- Alternates: absent
- Worktree linkage: absent; target reports only its own worktree
- Remote: local source `origin` removed immediately; final remote set is empty
- Hardlink proof: corresponding source and target pack files had different Windows file IDs (`...3b0000000d12ee` source, `...020000001c7585` target) and each hardlink enumeration named only its own repository path
- Pushes: none

Evidence is retained in `docs/fork-evidence/independent-clone-evidence.json`.

## Target Inventory

- Target path: `C:\Users\james\asp-model-studio`
- Final physical worktree files, excluding `.git`: 36,857
- Final physical worktree directories, excluding `.git` and the repository root: 4,685
- Final physical worktree bytes, excluding `.git`: 2,384,114,975
- Git-visible project files, including this report: 2,311
- Git-visible project directories: 553
- Git-visible project bytes, including this report: 548,983,599
- Fresh `.venv`: 20,640 files, 2,672 directories, 1,462,641,836 bytes
- Fresh `node_modules`: 13,905 files, 1,459 directories, 372,446,405 bytes

Generated `.runtime`, `.tmp`, pytest cache, `dist`, and `tsconfig.tsbuildinfo` outputs were removed after verification. Dependency directories remain ignored and uncommitted. Counts exclude Git administrative storage.

## Snapshot Verification

- Matching included existing files: 2,277
- Matching included bytes: 537,231,899
- Matching tracked deletions: 1
- Intentional exclusions: 32 (16 Git-visible untracked generated files and 16 modified tracked runtime/test-output deltas)
- Unexplained mismatches: 0

The initial clone checkout exhibited 1,182 working-tree byte differences caused by line-ending conversion. Every included source path was then copied byte-for-byte after baseline hash checks, and the full included-path verification passed before staging. Staging normalized EOL-only content away while preserving the exact intended 127 modifications, 17 additions, and one deletion.

## Fork-Snapshot Commit

- Hash: `17a6cbe541f481cd3d30a34711bc36ef0a8ae153`
- Message: `baseline: capture ATLAS working tree for ASP Model Studio fork`
- Parent: `e13ac139ec1d684935f50272f2c9cd3ef693ad9d`
- Commit contents: 145 paths, 20,873 insertions, 2,957 deletions

This commit is the exact safe fork point.

## Runtime Isolation

The credential-free launcher `scripts/start-asp-model-studio.ps1` is validation-only unless `-Start` is explicit. It refuses the financial ATLAS root, requires an independent `.git` directory, rejects Git alternates, requires distinct non-ATLAS ports, and never prints its session secret.

- Application title: `ASP Model Studio API`
- Instance/worker IDs: `asp-model-studio-local` / `asp-model-studio-local-worker`
- Session cookie: `asp_model_studio_session`
- Frontend/backend/preview ports: 5274 / 8101 / 4274 (inherited ATLAS ports are rejected)
- Compose project: `asp-model-studio`
- Persistence/security databases: `.runtime/asp-model-studio/persistence` and `.runtime/asp-model-studio/security`
- Mutable roots: datasets, backups, checkpoints, evidence, feature manifests, model registry, scoring runs, VIF plans, restricted metadata, bureau catalogs, results, uploads, logs, caches, Python/SAS runtime, and temporary files all resolve beneath `.runtime/asp-model-studio`
- Authentication defaults: enabled, no public registration, no dev-user header, no local-user bootstrap, loopback-only start commands

Some inherited stores remain repository-relative or do not yet consume the reserved ASP variables. The independent clone keeps those paths target-local; the launcher isolates every configurable authority and blocks unsafe source execution. No service was launched during this fork.

Direct Vite defaults use the target ports, E2E seed helpers resolve data from the target repository and default to port 8101, and the inherited `sync:atlas` entry point is fail-closed. The only executable reference to the financial source path is the launcher's explicit refusal guard.

## Dependency Rebuild

- Python: 3.12.6 in a fresh target `.venv`; pip 24.2
- Root `requirements.txt`: deterministic resolution failure because `pyarrow==25.0.0` conflicts with `mlflow==2.17.0` (`pyarrow>=4,<18`)
- Focused Python environment: repository CI-used `server/requirements.txt`, plus exact root-declared pins required by the eager server import and focused tests (`pyarrow`, `duckdb`, `polars`, `joblib`, `httpx`, `pytest`)
- Python package consistency: `pip check` passed
- Python full lock: absent; root/server requirement files conflict for FastAPI, Pydantic, Uvicorn, pandas, and SciPy
- Node: 24.3.0; npm 11.6.4
- Node install: `npm ci` passed; direct dependency graph passed
- CI difference: repository CI declares Node 20
- Lock/manifests: `package-lock.json`, `requirements.txt`, and `server/requirements.txt` hashes remained unchanged

No package version file was modified and no source dependency directory was copied.

## Verification

Passed target checks:

- validation-only launcher with isolated paths, unique ports/cookie/identity, both dependency stacks ready, and zero remotes;
- backend import (`ASP Model Studio API`, 495 routes);
- `pip check` and Python `compileall`;
- TypeScript no-emit check;
- static storage-isolation guard over 135 Python test sources;
- frontend project-type, workflow-library, monitoring-center, and regression suites (30 Node tests plus the monitoring backend test);
- nine fresh-process hermetic backend suites: security containment, canonical dataset identity, project access, storage isolation, model-registry durability, sealed-holdout isolation, persistence authorization, monitoring, and project/dataset activation (9 passed, 0 failed);
- production TypeScript/Vite build (3,451 modules; initial 53.91 seconds, final isolation rerun 26.73 seconds).

Known inherited failure:

- `tests/experimentCanonicalIdentity.test.mjs`: 3 passed, 3 failed. Two fixtures omit the now-required governed preprocessing contract, and one source assertion expects `loadCanonicalPreparationBrowserState`, which the captured implementation no longer imports. Neither the implementation nor this test was changed by the fork-specific commit.

A preliminary combined pytest collection produced 15 failures and 123 passes because multiple suites mutate import-cached authorities in one process and the target launcher deliberately places temporary storage inside the target. The valid rerun used the repository's hermetic runner with a separate source mirror and authority set per suite; all nine suites passed. The combined run also revealed one real fork regression—an over-broad public health payload—which was repaired before the passing hermetic security run.

Build warnings were limited to stale browser-compatibility metadata, large chunks, and a module imported both statically and dynamically. Live startup, Playwright E2E, provider/network tests, and the full security inventory that launches Uvicorn were intentionally not run. Exact evidence is in `docs/fork-evidence/verification-summary.json` and `backend-hermetic-run-summary.json`.

## Secret and Artifact Audit

The snapshot staged audit found no forbidden path and no secret; one loopback credential-shaped URL and generic token/password identifiers were resolved as test fixtures or code identifiers. The final staged-content audit checked for private-key/certificate blocks, high-confidence credential assignments and URLs, `.env` additions, databases, dependency/build/runtime directories, ASP paths/data, and source-directory links. It found no secret or prohibited newly staged artifact.

No `.env.local`, credentials, private keys, certificates, local databases, copied runtime artifacts, ASP files, raw sports data, sportsbook keys, or Odds API credentials are included. The target does inherit 764 already tracked files under `server/artifacts` from ATLAS history; these were not copied from local runtime state and no generated dirty delta was committed.

## Financial ATLAS Post-Fork Integrity

- Branch: `codex/phase2a-canonical-lineage` (unchanged)
- HEAD: `e13ac139ec1d684935f50272f2c9cd3ef693ad9d` (unchanged)
- Index fingerprint: `4ed8f33a26ece67b4b1b19066b6001134ddbc1a717186aedcf65934d773f926a` (unchanged)
- Status fingerprint: `53feb055ccaaf181aa76c222d02cae02de05093a76920c7bfbbe3bacc9564d6c` (unchanged)
- Manifest comparison: 2,309 existing files and 567,525,939 bytes matched; the tracked deletion matched; unexpected paths, missing paths, and hash mismatches were all zero
- Stable during the post-fork audit: yes
- Exact unchanged decision: **true**

The full result is in `docs/fork-evidence/postfork-source-verification.json`.

## ASP Isolation

`C:\Users\james\ai-sports-predictor` was not accessed, inspected, executed, copied, or modified. No ASP file, database, Parquet warehouse, provider key, runtime, service, model artifact, report, or Git history entered this fork. Future communication must use immutable dataset manifests, governed model bundles, and forward-evidence contracts—never shared mutable storage.

## Final Target Git State

- Branch: `main`
- Fork-snapshot commit: `17a6cbe541f481cd3d30a34711bc36ef0a8ae153`
- Provenance/isolation commit: the commit containing this report, message `chore: establish ASP Model Studio isolation and provenance`
- HEAD: the provenance/isolation commit on `main`
- Worktree: clean after commit
- Remotes: none
- Alternates/worktree linkage: none
- Push: none

A Git commit cannot contain its own literal hash without changing that hash. The exact provenance/isolation commit and final HEAD hash are therefore recorded in the final command evidence and handoff immediately after this report's commit is created.

## Next Permissible Step

The next phase is an independent **ASP Model Studio sports-domain architecture and rebranding assessment**. This fork did not begin that phase.
