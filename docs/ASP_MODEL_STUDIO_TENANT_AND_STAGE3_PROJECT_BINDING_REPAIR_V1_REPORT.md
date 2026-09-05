# ASP Model Studio tenant and Stage 3 project binding repair V1

Captured 2026-09-05T20:30:23.332798+00:00.

Partial readiness. Canonical objects are published; the prepared membership and ACL repair remains unapplied.

1. **Starting worktree, branch, and full HEAD.**

    Implementation base: `C:\Users\james\asp-model-studio\.tmp\asp-player-prior-wave2`, `codex/mlb-player-prior-wave2`, `bff19a8a657bc96dea0469fad481acdcb4234386`. The protected primary checkout was independently found on `codex/mlb-governed-prior-engine-v1` at `33cd85fa5074efeec3077036baea9c8b2ef86bdf`; it was not used as the implementation base. The read-only audit is `3a70c98b485a6e9450782ad6d296add0ea7f49d6`, confirmed docs-only relative to Wave 2. [initial-git-reconciliation.json](<C:/Users/james/worktrees/asp-model-studio-tenant-workflow-repair-v1/docs/repair-evidence/initial-git-reconciliation.json>)

2. **New worktree, branch, and final full HEAD.**

    `C:\Users\james\worktrees\asp-model-studio-tenant-workflow-repair-v1`, branch `codex/model-studio-tenant-workflow-repair-v1`. Verified source/test commit: `2fb8c66854e999a66847d959a297cf5d67c410e4`. The documentation commit contains this report; its final full HEAD is recorded immediately afterward in the [post-commit Git receipt](<C:/Users/james/worktrees/asp-model-studio-tenant-workflow-repair-v1/.tmp/repair-final-git-state.json>) and the final response, avoiding a self-referential commit hash.

3. **Main HEAD.**

    `924db29511f93909f9d785855bfa056775443690`; unchanged.

4. **Git status before and after.**

    All six original relevant checkouts were clean, including no reported untracked files. The new worktree began clean at the exact Wave 2 base. Final source, tests, and documentation are committed only on the repair branch; the [post-commit Git receipt](<C:/Users/james/worktrees/asp-model-studio-tenant-workflow-repair-v1/.tmp/repair-final-git-state.json>) records its final status and complete commit list. Generated disposable test/build dependencies and the final Git receipt are ignored local files. [final-reconciliation.json](<C:/Users/james/worktrees/asp-model-studio-tenant-workflow-repair-v1/docs/repair-evidence/final-reconciliation.json>)

5. **Preserved worktrees and untracked files.**

    All six original registered worktrees retain their original branches, HEADs, and Git status, including the protected primary, Wave 2, interaction, remaining-feature, and two audit worktrees. All 40 source prior JSON files are byte-identical. No existing user file was moved, deleted, staged, or fabricated; the two previously missing user filenames were not recreated. [final-reconciliation.json](<C:/Users/james/worktrees/asp-model-studio-tenant-workflow-repair-v1/docs/repair-evidence/final-reconciliation.json>)

6. **Exact audit findings addressed.**

    F-001 (P0 self-grant project takeover), F-004 (unauthorized ACL/membership visibility), and F-006 (unscoped Stage 3 routes) were read from the exact audit and independently reproduced. F-006 received route and cache repairs. F-001/F-004 have prepared source/test patches but remain unfixed in the current repair branch because automatic approval review rejected applying them. This is a partial repair, not tenant-security certification.

7. **F-001 reproduction before repair.**

    A disposable administrator and two ordinary users, each initially owning two projects, reproduced HTTP 200 for User A granting themselves ownership-equivalent access to User B's project, then HTTP 200 reading it. Connected probes reproduced guessed-ID grants, existing-ID creation takeover, owner replacement through PUT, and a grant surviving audit failure. Across 29 checks, 13 passed and 16 failed; some later failures follow earlier takeovers, rather than representing 16 independent defects. [tenant-security-before.json](<C:/Users/james/worktrees/asp-model-studio-tenant-workflow-repair-v1/docs/repair-evidence/tenant-security-before.json>)

8. **F-001 result after repair.**

    NOT REPAIRED / NOT AFTER-TESTED. The six-file source patch and separate 30-probe test patch pass dry-run application checks but were not applied. Source patch SHA-256: `9aed4725c1a387eae823b61bce0f32387b37cff68eeb79226ddbfbe6d035889b`; test patch: `cbdb58f3ef735eebc30bf517ddfdea009548807620986671b1fd1d8a933c7080`. [tenant-security-pending-status.json](<C:/Users/james/worktrees/asp-model-studio-tenant-workflow-repair-v1/docs/repair-evidence/tenant-security-pending-status.json>) [TENANT_SECURITY_PATCH_REVIEW.md](<C:/Users/james/worktrees/asp-model-studio-tenant-workflow-repair-v1/docs/repair-evidence/TENANT_SECURITY_PATCH_REVIEW.md>)

9. **F-004 result.**

    The exact base returned HTTP 200 for a foreign ACL read. The affected endpoint and underlying membership/ACL code remain unchanged. No post-repair pass, timing-equivalence proof, or closure is claimed.

10. **F-006 result.**

    The base allowed foreign-project cockpit preview and reached a synthetic data reader with HTTP 200. Repaired active routes require authenticated, exact-project scope before reaching data/services; foreign and anonymous probes now fail closed. This closes the missing route checks in tested scope, but F-001 still permits acquiring unauthorized membership and therefore prevents end-to-end tenant-isolation closure. [f006-adversarial-results.json](<C:/Users/james/worktrees/asp-model-studio-tenant-workflow-repair-v1/docs/tenant-stage3-repair-v1/f006-adversarial-results.json>)

11. **Number of Stage 3 routes inventoried.**

    99 Stage 3 routes, plus 20 project configuration/support routes. Each method/path, dependency, and retirement status is enumerated. [authorization-route-coverage.json](<C:/Users/james/worktrees/asp-model-studio-tenant-workflow-repair-v1/docs/tenant-stage3-repair-v1/authorization-route-coverage.json>)

12. **Number proven project-authorized.**

    90 active project-bearing Stage 3 routes use the canonical authorization dependency. The other 9 are existing authenticated retired routes. The 20 supporting project routes are also checked. These are dependency/probe results, not a claim that the unapplied membership fix is present.

13. **Cross-user probes and result.**

    180 foreign-user HTTP probes, 90 anonymous probes, and 20 supporting foreign-project probes passed within the 338-test focused route suite. The fixture has two simultaneous ordinary users with two projects each. Existing Gen3 ACL tests: 3 passed and 2 skipped for absent real runtime objects; existing artifact router tests: 2 passed. All new checks use synthetic records.

14. **Cross-project probes and result.**

    Disposable tests reject path/query/nested-body project conflicts, foreign dataset/policy/split/feature/candidate/finalist/artifact references, mismatched copied jobs/plans/receipts, revoked worker authority, and cross-user/project cache reuse. Accepted science follows the exact selected split's features and adopted policies, with no independently selected latest/global authority. A nonpilot three-fold artifact contract fails on the exact base and passes after repair. [workflow-focused-probes.json](<C:/Users/james/worktrees/asp-model-studio-tenant-workflow-repair-v1/docs/repair-evidence/workflow-focused-probes.json>) [route-results.xml](<C:/Users/james/worktrees/asp-model-studio-tenant-workflow-repair-v1/docs/tenant-stage3-repair-v1/route-results.xml>)

15. **Wave 2 source artifact root.**

    `C:\Users\james\asp-model-studio\.tmp\asp-player-prior-wave2\.runtime\asp-model-studio\stage3-player-prior-authorities-v2`. All 40 original JSON files, including unreferenced older objects, remain intact.

16. **Canonical destination root.**

    `C:\Users\james\asp-model-studio\.runtime\asp-model-studio\stage3-player-prior-authorities-v2`. The root was absent before publication. Repair code independently authenticates this root against read-only canonical project metadata. The protected primary checkout predates the V2 resolver and was not integrated or restarted; availability of canonical objects does not imply operational deployment.

17. **Wave 2 authority identities and hashes.**

    Authority: `MLB_PLAYER_STATE_PRIOR_AUTHORITY_V2:sha256:9d9cfaf34f87be67f7d3ab2b8b024d83a6fc5e8abe0dde8de7be0866f1b8366e`.

    Final development: `MLB_PLAYER_STATE_FITTED_PRIOR_V2:FINAL_DEVELOPMENT:sha256:5ae0f9f560f83935e1f89440657ac4080afc33ac3318c3c2c8e50656a9eee526`.

    Authority object SHA-256: `bac2d184d88b0a7b2b395951d7b8b7d50f493ea967539f6c75110ef9e5534bec`. Definition checksum: `ee80dae2687051bcc02786e7ad1ec7ccc50a8f2583ca7857a05db679b12b5045`. Fold-contract checksum: `cd72058500333f9fae8dcb11867dbc674a015f2c84585ccb3cd81bf62c437d31`. Output-contract checksum: `19cb923fafcfa98d946f9702b9e34f95bcee5516992d8e70818af3115431c102`. Gold parent: `67de02ce19738b29953341151640fb69244b764b0e532b687ab6bacedbb3f758`. Companion parent: `98673b65dc5eab61e39b16d1313c27bbb2cf908c525f80db579cb07a5cfdab33`.

    Fold 1: `0d35d54561459534e73edb7a63271e133b64782a6ed459838a37f19243fbf4c6`.
    Fold 2: `6d0b453ec2cb1eaaa8044918ff3d13f3e883bf725407c16af92c17cc1b533c15`.
    Fold 3: `13aa1f8c2e14db935250b84be5c297e15654d619627563503c4bb50323356d6c`.
    Fold 4: `5b5524d092cc7868fd5c32750a6d8555783a989c559adeeeb3bad9b36b69f3e4`.
    Fold 5: `599ad47c6ec704d349f4c766260070d4d423b27ddee404cb33ebb98b1608f2af`.

    Independent resolution authenticates 11 V1 and 10 V2 features, all five fitted folds, final development, 3 retired fields, and zero missing prior-evidence blockers. Rights remain the original most-restrictive intersection, governed local research only. [canonical-publication-receipt.json](<C:/Users/james/worktrees/asp-model-studio-tenant-workflow-repair-v1/docs/repair-evidence/canonical-publication-receipt.json>) [canonical-resolver-independent-verification.json](<C:/Users/james/worktrees/asp-model-studio-tenant-workflow-repair-v1/docs/repair-evidence/canonical-resolver-independent-verification.json>)

18. **Objects copied versus reused.**

    First publication: 9 exact existing objects created, 0 reused, totaling 181,163 object bytes, plus one project locator. Only the authenticated current closure was published; 30 unrelated source objects remain source-only.

19. **Publication writes.**

    Writes were bounded to content-addressed canonical object JSON, the project locator, and repair receipts. Child objects were published before the parent manifest; the locator was last. Atomic no-overwrite publication rejects collisions and linked paths. Existing project registration already authenticates the same identity, so zero database registration/publication events were needed. No refit or new scientific identity.

    The Windows publisher pins directory ancestors against rename/deletion while publishing. It assumes an operator-controlled destination; it is not certified against a hostile local writer changing an empty directory's reparse state in place. Non-Windows publication fails closed. [canonical-publication-receipt.json](<C:/Users/james/worktrees/asp-model-studio-tenant-workflow-repair-v1/docs/repair-evidence/canonical-publication-receipt.json>)

20. **Idempotent replay result.**

    Replay authenticated and reused all 9 objects, created zero objects, and left the existing locator unchanged. Source and destination bytes and hashes were independently checked; all eight required tamper families, collision and publication-order tests passed in disposable roots.

21. **Final-OOT access before/after.**

    Authoritative final-OOT opens and target reads: 0 before / 0 after; `targetColumnsRead=[]`. Holdout-exposure and dataset-query-audit rows remain zero. One early metadata probe attempted an old EDA Parquet open; the guard blocked it before opening, and the probe was replaced by metadata-only resolution. The explicitly live OOT test was deselected. Broad-suite evidence uses Python plus known-reader guards and source review, not exhaustive OS syscall tracing. [final-oot-and-scientific-boundaries.json](<C:/Users/james/worktrees/asp-model-studio-tenant-workflow-repair-v1/docs/repair-evidence/final-oot-and-scientific-boundaries.json>) [final-reconciliation.json](<C:/Users/james/worktrees/asp-model-studio-tenant-workflow-repair-v1/docs/repair-evidence/final-reconciliation.json>)

22. **Current Gold mutations.**

    0. Gold and sufficient-statistics manifest hashes remain exact. The 28 protected logical database table counts and row digests are identical, and SQLite integrity returns `ok`. No operational migration or service restart occurred.

23. **Treatment policy state.**

    Challenger treatment remains DRAFT; adoption is blocked and no policy was adopted. Existing pilot adoption evidence remains unchanged. Rivalry was not approved, activated, inferred, or populated.

24. **Feature-set registrations.**

    0 authoritative feature-set registrations. Existing project registrations were read and authenticated only.

25. **Predictive model fits.**

    0 authoritative predictive fits, tuning runs, scoring runs, calibrations, promotions, or champion mutations. Synthetic execution-plumbing tests used disposable projects and roots only; their fits are not authoritative project activity. Provider calls: 0.

26. **Pilot project result.**

    The generic registered-project ready flow is retained. Five sealed historical pilot run receipts and their registered split/features/policies authenticated through the opt-in metadata-only reader. Real pilot row-derived controls were not exercised in the browser: their pre-existing EDA resolver opens/hashes partitions that include final OOT. Pilot live-control compatibility therefore remains NOT VERIFIED; no bypass was added and no evidence was rewritten.

27. **Deliberate challenger downstream-page result.**

    PASS for all seven downstream pages in the authenticated disposable metadata-clone application. The actual built frontend displays MLB 2026 Current-Data Challenger v2 — Deliberate Development (asp-mtlozhdx), 683,662 development rows, 14,067 locked OOT rows, authenticated prior identities, and DRAFT treatment. Queue controls remain disabled with reasons; evaluation/refinement have truthful empty states and calibration/simulation remain blocked. Page navigation creates no model job. This is the repaired worktree's isolated application, not a claim that the protected running primary is updated. The actual labels are 9 Model Development Laboratory; 10 Candidate Evaluation; 11 Model Refinement & Explainability; 12 Calibration; 13 Simulation & Game-Level Evaluation; 14 Champion/Challenger Decision; 15 Registry, Export & Implementation. Step 15 shared the project-bound science root cause and was repaired without redesigning the registry.

28. **Confirmation that no pilot evidence appeared in the challenger.**

    PASS within the exercised challenger views, simultaneous sessions, user switching and deliberate foreign-project denial views: no pilot candidate, run, finalist, or champion evidence appeared in the challenger. User-authored notes and selections can persist; server-derived cached results, simulated evidence, suites, profiles, and completed-step flags are not restored from old cockpit snapshots. Existing stored originals are not rewritten on read. No literal pilot project ID remains in production server/src/scripts.

29. **Tests.**

    The full backend runs completed in source-only disposable mirrors under identical guards. Exact bff baseline: 2,287 passed, 477 failed, 330 skipped, 127 errors, 1 deselected. Candidate-2: 2,680 passed, 480 failed, 330 skipped, 127 errors, 1 deselected. Pytest error phases can overlap case outcomes; these are its headline counts. All 3,197 shared result nodes preserve their outcome, and all 934 shared nonpass-phase reasons match after documented normalization. No original collected tests were removed; 396 new tests were added, of which 393 passed. Three new publication tests were blocked when the full harness hid existing ancestor directories and treated a resulting mkdir attempt as an external write. The unchanged publication implementation passes all 24 focused disposable tests; no source workaround was made for this harness constraint. The prohibited live database/OOT test was explicitly deselected. The final catalog projection is a later one-file follow-up, separately tested 8/8 and checked through the scratch application; it is not represented as part of the frozen full candidate snapshot. These constrained comparisons establish no newly observed product regression, not a clean full suite. Per-case and normalized-reason receipts enumerate every nonpass. [full-backend-comparison.json](<C:/Users/james/worktrees/asp-model-studio-tenant-workflow-repair-v1/docs/tenant-stage3-repair-v1/full-backend-comparison.json>) [full-backend-nonpass-reasons.json](<C:/Users/james/worktrees/asp-model-studio-tenant-workflow-repair-v1/docs/tenant-stage3-repair-v1/full-backend-nonpass-reasons.json>) [catalog-projection-followup.json](<C:/Users/james/worktrees/asp-model-studio-tenant-workflow-repair-v1/docs/tenant-stage3-repair-v1/catalog-projection-followup.json>) Copied JUnit text has only empty-line trailing-whitespace normalization; original runner reports are preserved and hash mappings are recorded in [report-artifact-normalization.json](<C:/Users/james/worktrees/asp-model-studio-tenant-workflow-repair-v1/docs/repair-evidence/report-artifact-normalization.json>).

    Focused route tests: 338 passed. Publication: 24 passed. Workflow/artifact/game subset: 42 passed. Catalog projection follow-up: base 2 failed/6 passed; repaired 8 passed. These overlap broad-suite cases and must not be added to a headline suite total. Three additional frontend render probes reproduce the placeholder-project error on exact base and pass after repair.

    Full frontend: 165 files enumerated, 163 executed, 112 pass files. Named cases: 1,097 passed, 56 failed. All 51 nonpass files were rechecked against exact bff under the same guard: zero introduced observed named failures and zero changed normalized reasons. Failures span 43 assertion/runtime, 7 dependency-unavailable and 1 guard-blocked files; 2 specialized files were excluded. Sixteen top-level aborts leave later assertions unreached, so this is not a clean/full-coverage pass.

    Python compilation: 541 server/scripts files, zero failures, without importing application code or writing bytecode. SQLite integrity and diff checks pass. [frontend-suite-comparison.json](<C:/Users/james/worktrees/asp-model-studio-tenant-workflow-repair-v1/docs/repair-evidence/frontend-suite-comparison.json>) [workflow-verification-summary.json](<C:/Users/james/worktrees/asp-model-studio-tenant-workflow-repair-v1/docs/repair-evidence/workflow-verification-summary.json>) [prior-publication-tests.xml](<C:/Users/james/worktrees/asp-model-studio-tenant-workflow-repair-v1/docs/repair-evidence/prior-publication-tests.xml>) [python-compilation.json](<C:/Users/james/worktrees/asp-model-studio-tenant-workflow-repair-v1/docs/repair-evidence/python-compilation.json>)

30. **TypeScript/build.**

    TypeScript and modeling production build passed with `VITE_API_BASE=/api`. Main asset `dist/assets/main-C4SfSlYd.js`, SHA-256 `dfca0032e3b152434cfb8cfb8d08262e0c9a3bedf38c3fa538ba3e38e702a520`. Nonfatal warnings: large main bundle, outdated browser compatibility metadata, and mixed static/dynamic cockpit imports. [workflow-verification-summary.json](<C:/Users/james/worktrees/asp-model-studio-tenant-workflow-repair-v1/docs/repair-evidence/workflow-verification-summary.json>)

31. **Browser acceptance.**

    331/331 assertions passed at 1920×1080, 1024×768 and 390×844, using the actual built frontend and actual cookie authentication against the actual FastAPI application in a disposable metadata clone. All seven pages, explicit project selection, login return path, visible navigation, refresh/back/forward, deep linking, control fit, disabled reasons, drawers and focus return passed. There were zero unexpected entitled-navigation console errors and zero page-script errors. Five expected unauthenticated-authentication errors and four intentional access-denial errors remain categorized in the receipt. There were zero placeholder-project, external application, or EDA/row requests. All scientific tables, canonical/run JSON, job coordinator state and scientific runtime files remained unchanged; 84 project and 84 workflow presentation autosaves changed only the scratch fixture, alongside synthetic-user activity. Original cloned user records stayed unchanged. The owned test service stopped. This fixture copies 25 allowlisted metadata tables, uses synthetic accounts, and disables app lifespan to avoid operational startup scans. Guard evidence is application-level instrumentation, not exhaustive OS telemetry. Pilot live row-based controls and operational startup are NOT VERIFIED. See [browser acceptance and limits](<C:/Users/james/worktrees/asp-model-studio-tenant-workflow-repair-v1/docs/repair-evidence/browser/README.md>), [all assertions](<C:/Users/james/worktrees/asp-model-studio-tenant-workflow-repair-v1/docs/repair-evidence/browser/acceptance.json>) and [preservation guard receipt](<C:/Users/james/worktrees/asp-model-studio-tenant-workflow-repair-v1/docs/repair-evidence/browser/guard-receipt.json>). Twenty-nine screenshots and the sanitized reproduction harness are included.

32. **Files changed.**

    54 source/test files changed in the isolated worktree, plus verification documentation. Changes cover canonical project authorization and cache partitioning; catalog season projection; publication adapter/resolver; exact project science/jobs/artifacts; downstream frontend state/navigation; focused tests and adapted relevant fixtures. Every source/test path, byte size and SHA-256 is listed in [files-changed.json](<C:/Users/james/worktrees/asp-model-studio-tenant-workflow-repair-v1/docs/repair-evidence/files-changed.json>). No protected security patch file was applied, and no primary application source was modified.

33. **Commits created.**

    `d91fcd0ff12b0e4d6f3634579b5c39f144e11d29` — fix(stage3): enforce project scope across downstream routes.
    `4d77f5e6d81cd7bb6e13037a04fb7f7849e22e44` — feat(stage3): publish canonical Wave 2 prior runtime authority.
    `40fd704983404a781af18ecda4ad8faded413852` — fix(stage3): generalize downstream workflow to active project.
    `2fb8c66854e999a66847d959a297cf5d67c410e4` — test(stage3): prove tenant isolation and project-bound execution.

    The final `docs: implementation and verification report` commit is recorded in the [post-commit Git receipt](<C:/Users/james/worktrees/asp-model-studio-tenant-workflow-repair-v1/.tmp/repair-final-git-state.json>). The requested security commit could not be created because its source/test patches remain unapplied. No empty or misleading security commit was made.

34. **Pushes performed.**

    0 pushes, 0 merges, 0 rebases, 0 history rewrites. Main and every original checkout remain unchanged.

35. **Remaining treatment blockers.**

    The schedule authority lacks original pregame knowledge timestamps and an independent {0,1,2} doubleheader-sequence invariant tied to scheduled start order. The holiday calendar lacks a separately registered, sourced, effective-dated authority; null does not prove NONE rather than UNKNOWN_HOLIDAY for all venue regions. Both remain unresolved by design. The rivalry field remains held closed because the reviewed workbook supplies no recommendation.

36. **Remaining workflow blockers.**

    F-001/F-004 remain open and undermine end-to-end tenant isolation. The protected running primary does not yet contain this repair. Challenger execution remains blocked on governed treatment prerequisites; new artifact production currently supports XGBoost only, and game scoring still requires governed lineup/starter authority. Real pilot row-derived controls are not browser-certified under the zero-OOT boundary. Broad suites have documented baseline/environment nonpasses and unreached assertions. No full readiness or deployment approval is implied.

37. **Exact next step for returning to challenger model development.**

    First obtain the narrow approval needed to apply the two already prepared membership/ACL patches only in this repair worktree, then rerun disposable security, route and affected frontend checks and create the security commit. Review the complete repaired branch before any separately authorized integration/deployment. In a separate governed task, resolve the schedule and holiday authority blockers while keeping rivalry closed, then explicitly approve the required treatment/feature prerequisites. Only after those gates pass should an authorized challenger model-development run be queued. This task performed none of those governance or operational actions.

38. **Final verdict.**

    **ASP_MODEL_STUDIO_REPAIR_PARTIALLY_READY**. Canonical publication and bounded project workflow/route work are implemented and evidenced, but F-001/F-004 are not closed. Automatic approval review rejected the narrow security apply operation twice, citing older backup-only restrictions despite the later repair attachment. The rejected action was not bypassed; specific approval to apply the prepared source/test patches is still required.
