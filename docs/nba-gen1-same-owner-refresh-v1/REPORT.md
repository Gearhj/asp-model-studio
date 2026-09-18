# NBA opening-night operational readiness

| Area | Status |
|---|---|
| Publisher implementation | READY — all-game dispatch, immutable revisions, cumulative discovery and recoverable per-game journals |
| Input-refresh implementation | READY — same owner/lock, bounded conditional transport, versioned atomic admission, durable phase receipts |
| Live acquisition authorization | PENDING — exact immutable proposal and inactive grant template supplied; zero requests executed |
| Installation and consumer activation | PENDING — installer Plan verified; NBA owners 0; no consumer activation |

Deployment `34b4060ff4ae4609f4fb61a2c5bd8518fa0587396e5cd1c489d78ec411d8ccf6` has 35 verified members, source commit `a4f3058759889a7fa8406a12a49ab1b905541ae4`. The prior deployment remains preserved and uninstalled. REFRESH_PLAN physical SHA is `f2210fc0d987653bea57db0d37c170db6efde6d021bc2cb53cb32a3eb16ee863` (10785 bytes). Its proposal binds the deployment and physical manifest; neither is approval.

Focused verification: **28 tests passed**, covering no-network/default/not-due behavior; conditional unchanged capture; changed-content admission; precommit rejection; stale/post-tipoff checks; multi-game dispatch; interruption after capture and admission; restart without duplicate requests or forecasts; interrupted unknown transport quarantine; access refusal/schema drift; budget and grant gates; DST; immutable discovery and preserved forecast bindings. Fixture transports and synthetic scores are not source evidence. The prior synthetic renderer checks 10,000 draws without fitting. No real forecast or model run occurred.

The exact packaged Windows PowerShell 5.1 wrapper ran locally once with disabled networking and isolated state/discovery. Python exit 0, wrapper exit 0, REFRESH_NOT_DUE, REUSED_ADMITTED_VERSION and NOT_DUE. Launcher SHA `7350cbc5b8eb08516627d6e7c7c86ccba3afd1a45953cb2c24c88d153a26d3c0`; owner receipt SHA `093e00c6fd1435a24437aebf8e9e526765e6ba495ca6bd13cc38b619c921f6ac`; runner SHA `df8e7050cba477c7833c08a293342ea6dcc2f92058c42ef1a6157d1e8e935a53`. This is local plumbing evidence, not a natural scheduled run. There are no source requests or new captures.

All **61** bound prior forecast/model objects remain byte-identical. The three unrelated ASP task definitions match before/after; no NBA task was created. No AISP writes, provider calls, response bytes, paid costs, Windows elevation attempts, model fits, forecast publications, decisions or positions. Only a new additive metadata handoff is eligible for exchange publication.

Real retained schedule: **1206 rows; 1197 supported identities; 9 explicit exclusions** ({'NEUTRAL_HISTORY_ONLY': 3, 'UNMAPPED_TEAM': 5, 'NOT_STANDARD_REGULAR_GAME': 1}). Frozen history has 8289 games. The retained capture is September 14; it must be actually revalidated and admitted before October publication. All 1197 supported identities are currently NOT_DUE; stale-input reasons remain in the inventory. The source release metadata provides no reliable update SLA. A missing final or unrecognized schema can still block a game/slate even after authorization.

Earliest legitimate network opportunity: **2026-10-13T18:00:00+00:00 / 2026-10-13T14:00:00-04:00**. First publication checkpoint: **2026-10-13T19:00:00+00:00 / 2026-10-13T15:00:00-04:00**. These derive from the current captured first tipoff and are subject to source schedule revisions, authorization and installation. No artificial early forecast was created to demonstrate activity.

Next dependency: James approval of this exact refresh plan/proposal and final deployment, followed by supported Administrator installation as the intended owner and natural-run verification. AISP's consumer owner then validates/pins/activates separately. See ACTIVATION.md for exact commands and rollback to no NBA task. No second scheduler or unspecified data owner remains in the design.
