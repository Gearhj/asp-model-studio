# V18 current-state pipeline: real pregame research publication

## Outcome

Starting branch/commit: codex/market-intelligence-rff-research-v1 / d68ac6b1eea3f1174d929c74984312d9dd51436d.
Implementation branch: codex/mlb-v18-current-state-pipeline-v1.

The accepted V18 model now has an immutable executable registration and has scored a real upcoming game. PIT–CWS was published on September 10 at 17:19:31 Eastern, before its 19:40 first pitch. Its 5,000 simulations completed legally, with exact paired 64-game replay. This is actual current-source inference, not the earlier synthetic execution fixture.

Both COL–NYY and PIT–CWS now have 34 supported templates each: 18 starting-lineup matchups and 16 current active pitching-staff templates, all 246 raw fields supported per template. Both games are now published: COL–NYY completed at 17:29:52 Eastern before its 19:05 first pitch. The final aggregate contains two valid forecasts, zero skips and zero failures. PIT's original object was reused with no additional PIT inference.

V18 remains RESEARCH_SHADOW, NOT_PROMOTED, with no wagering authority. No model, calibration or treatment was fitted. AISP's observed Gen1 path remains asp_mlb_ensemble / 2.0.0-gate2-08cca634c81b. No AISP forecast, code, persistence, policy, position, settlement or service was changed.

## Approved source scope and implementation

James explicitly authorized separately acquired, finalized-game source history from August 14–27 solely to construct current pregame rolling inputs. This does not authorize opening sealed Final OOT evaluation artifacts, evaluating/selecting models on that period, or claiming reconstructed data were available at historical forecast times. New operational receipts are authenticated before those source dates are permitted. Legacy evaluation files and row groups remain unread.

The implemented path is:

1. Explicit-opt-in, bounded free source acquisition with immutable raw payloads, original source clocks, corrections/catch-up accounting and content-based reuse.
2. Frozen FD1 annual-prior loading and canonical player/team crosswalks; read-only current schedule, starter, lineup and active-roster capture.
3. Independently counted exposure in the accepted 2019-forward PA source universe and exact player last-100-PA/last-250-BF windows. Verified source-only children before August 14 join the separately acquired August 14-forward operational archive.
4. Accepted annual, rolling, pitch-composition, float64 velocity, team-context, calendar, handedness and simulated-state calculations. A selected player-window extract is not called a complete global archive. Sparse windows require exact equality with independently counted player exposure; unknown evidence cannot become a cold/zero state.
5. Immutable raw246 snapshots, treated273 contracts and 21 frozen prior paths. Instance-local prospective transformation authority wraps the frozen preprocessor, without changing fitted rules or training/OOT guards.
6. Accepted PA fold 5 and transition fold 4 inference, 5,000-game simulation, exact replay, current-clock checks before and after simulation, and the existing daily forecast serializer/research handoff.

Opposing-pitcher identity binding is corrected. The combined walk/HBP/catcher-interference class, separate OTHER_REACH, class order and Development treatment of 2025 remain unchanged. Same-day source games, including earlier doubleheader games, remain excluded. Cumulative exposure means accepted preceding PA rows since 2019—not career totals before 2019, season totals, annual FD1 totals or truncated window counts. Hypothetical simulator PAs are not observations. The active staff pool is not a claim about actual future reliever appearances; accepted removal/mixture rules remain unchanged.

## Exact feature coverage

Final supported COL/PIT compositions assign all 246 fields to category 1, ALREADY_AVAILABLE_CORRECTLY_MAPPED; unresolved counts in categories 2–8 are zero. Earlier 33/246 and 215/246 snapshots are preserved historical states, not final coverage. Structural missing states supported by frozen treatment are distinguished from observed numerical values.

All 213 previously unsupported raw fields are now resolved for these two games through source-backed calculation, mapping and approved current-history assembly. They were not 213 missing external feeds. No external-source blocker remains for these two published snapshots; other slates must independently satisfy their own participant, source and clock checks.

| Source/feature family | Fields |
|---|---:|
| Annual player priors | 25 |
| Completed PA/pitch windows and exposure | 31 |
| Team/schedule/venue context | 150 |
| Current schedule/calendar | 23 |
| Participant handedness | 6 |
| Simulated PA state | 5 |
| Canonical identity metadata | 6 |
| Total raw / frozen treated | 246 / 273 |

The machine-readable field contract retains definitions, entity grain, source identity, window, original clocks, accepted specification, transformations, missing/cold treatment and classification. Pitch composition retains the other/unclassified residual; velocity sum/sumsq remain float64. No selected feature was removed or replaced with a generic median/mode.

## Source evidence and real-game accounting

The authorized August 14–September 9 capture contains 54 daily schedule/Statcast receipts across all 27 dates: 370 completed games, 28,055 accepted PAs and 109,670 pitches. The first publication's selected current-player extract contains 40,310 PAs and 157,577 pitches after exact safe historical-window extension; it is not a new training population. There are 11,755 eligible FD1 BATTING/PITCHING rows from 2021–2025 and 2,322 projected full-season schedule identities without PA/outcome/lineup payloads.

Historical exposure adapter first current availability/ingestion: 2026-09-10T21:07:30.438839Z. First eligible live capture: 2026-09-10T21:12:24.335226Z, after source ingestion. Re-reading sources does not advance those source clocks or establish historical vintage.

| September 10 event | Canonical game ID | First pitch ET | Disposition |
|---|---|---|---|
| HOU–PHI | 8a0a0c75-60fc-478c-ba5d-5502ba52d2d2 | 13:05 | Earlier unsupported snapshot/skip retained; started during repair; no retrospective publication |
| TEX–SEA | 7946a01b-6daf-47b1-957b-edd64a316204 | 16:10 | Earlier missing-lineup skip retained; started before repair completed; no retrospective publication |
| COL–NYY | 147789ea-5c5e-4485-991b-289eb12a6f4a | 19:05 | Published 17:29:52; 5,000 legal simulations; exact 64-game replay |
| PIT–CWS | 1a36f34b-466f-4980-967f-fb9ba2778834 | 19:40 | Published 17:19:31; 5,000 legal simulations; exact 64-game replay |

PIT–CWS: PIT/away win 0.5718, CWS/home win 0.4282, expected total 8.1554. Forecast object SHA-256: dbce974760e2106b2fa23a7ef7fd348d67b261d06e690febae2556fa0dd12fdf.
COL–NYY: NYY/home win 0.643, COL/away win 0.357; expected scores NYY 4.8468 and COL 3.6106, total 8.4574. Forecast created 2026-09-10T21:29:52.660204Z; object SHA c87d341420ff02a6fe420c498b61472af5857015e6771f35d2f5b5706db69c3d. TB–ATL had already started before the earlier inventory and was never retrospectively scored.

COL's final blocker was Anthony Volpe, MLBAM 683011: the confirmed lineup had null batting hand. Although Gold encodes missing-hand indicators, accepted V18 explicitly rejects that state with SEMANTIC_HELD_REVIEW_REQUIRED. The failed diagnostic and original skip remain preserved; no frozen rule was relaxed. One free MLB Stats API current-player response confirmed bats R/throws R, observed/available/ingested at 2026-09-10T21:21:09.868087Z. Receipt SHA: b493e95dc2bfb095730e0f52c772af00eab519dcc4dcbfda018483d3db456edb; raw SHA: 1a248d916f1c820a020198bc7abe532c54dc528f2122913c3e8ef402650294e7. The independently timestamped canonical supplement does not overwrite the original AISP lineup. Historical PA batting side was not treated as authoritative current static handedness.

## Immutable identities and AISP import

Repository: C:\Users\james\asp-model-studio.
Output root: C:\Users\james\asp-model-studio\outputs\mlb-v18-current-state-pipeline-v1.
Below, object paths are relative to that output root unless stated otherwise. Raw source payloads and caches stay local/private, excluded from Git, with retained checksums and byte counts. Preserve those files when moving machines.

| Evidence | Immutable identity |
|---|---|
| Model registration | objects/sha256/b3e2f00f428fe5d1064f3c45562d7b3a644ce72bb372796abc500e023b25024e/v18-model-registration.json |
| Frozen PA/preprocessor/encoder | Repository outputs/mlb-v18-whole-game-challenger/sha256/a6e7e99122f1b60701a4728b97b32fcc11e03405bfd456ed6cd54f69b69adb27/executable/v18-pa-fold5.joblib; SHA 44ec4f457741f1aaeff42b81af1be5fd2712e494709ff1a0a8f0742b88d71c8b |
| Frozen transition | Same accepted bundle executable/transition-fold4.json; SHA 0e5e480f897ddefa5f9dddbc229a8a43bf29f7b81443c25ece611d9d4032b253 |
| Treatment | stage3-feature-treatment-spec-711fbb376e9a4d419f826de593195638; manifest 4d158e01a4a7d84fe6e7641f61edf0e9848f1775e025a2cec6c29cda22d479f3 |
| Exact accepted reload | objects/sha256/e83d4c57c7ff6dd1e45262c54f0cc7429ffd340f24447649e8d27671e893b312/accepted-reload.json |
| Authorized source attempt | sources/objects/sha256/70e17314a8cb15c1a3352af9e25d6eb51fa4bf59a5d1889ddc93add373801c26.acquisition-attempt.json |
| First real publication run | objects/sha256/284d38fda651c32668df4d434cc365f8326ef0d07e16ea3d3961d4a0fe91547b/complete-run.json |
| Preserved missing-hand hold | objects/sha256/c08c9456ab08ac29ae042a50f0f3e4993b8bbe68e9f1416d55a58e7e69cef462/missing-hand-frozen-hold-verification.json |
| Final actual publication run | objects/sha256/565432444ead71f1f985aea5936b5ea82014fdc0af471b15e8c3a4dde835c5aa/complete-run.json |
| Final raw246 field contract | objects/sha256/5b47e007954c43dc0ad9a7149b8507df9eb7245451a98d3fb1c6fd120631c0af/raw246-field-contract.json |
| Exact idempotent replay | objects/sha256/b756e73f56e3467325f83eccc2452220162ea285e553e0d0db44400b1af555b4/complete-run.json |

The first one-game handoff is handoffs/sha256/d4b2e21804d5e7e340f82f45e9649106a4ecff64588121933efc6878ee15da17/aisp-handoff.json, physical file SHA 9ffd69ac090f5d61643a1096acb3b76dea211c72b878dabf94d54b6085663f09. The completed two-game successor is handoffs/sha256/df620d9564e133b0b53dcdd75666c263069d93aa277476a70ab4abd289dc0666/aisp-handoff.json, physical SHA 791e5c53df79d8c3c26ca3a3514d1302dc402fea5d49024fb88133ceb3b0380a. It retains the original PIT forecast object without another PIT inference. Final slate receipt: slates/2026-09-10/sha256/edc583ee9e459720ee39e29aa9163b86c02ee68bf6a8e74bb683a788fe2e09fa/slate-result.json, physical SHA 87c0a9e4cab18bb3aad70aa678f4ade0652ae2eb1e4318962bbe0445f2cd452e.

AISP import action: consume only verified precomputed research forecasts and checksummed artifacts, leaving Gen1, official policy and positions unchanged; never execute/refit V18 in AISP. The current AISP importer incorrectly treats capturedAt as forecast availability for this path. Claude must preserve and use actual forecastCreatedAt for forecast availability, never earlier than creation, and retain capturedAt only as source/evidence cutoff. These timestamps already exist separately in the published object. This Model Studio run did not change AISP's importer or persistence; fix that mapping before claiming a correctly prospective AISP import.

Exact Claude instruction: in `server/app/shadow_import/mlb_v18_daily.py`, when `forecastCreatedAt` exists, require `capturedAt <= forecastCreatedAt < scheduledStart` and completion before the canonical actual first pitch. Set `available_as_of_utc=forecastCreatedAt`, keep `source_cutoff_utc=capturedAt`, and retain both clocks in lineage. Preserve legacy objects without the new field and do not rewrite historical rows. Verify the mapping with one focused timestamp/late-completion check, then use the existing importer and reimport once for idempotency. In the AISP server directory using its intended environment:

~~~powershell
python -m scripts.mlb_v18_daily_slate import --handoff "C:\Users\james\asp-model-studio\outputs\mlb-v18-current-state-pipeline-v1\handoffs\sha256\df620d9564e133b0b53dcdd75666c263069d93aa277476a70ab4abd289dc0666\aisp-handoff.json" --receipt "C:\Users\james\asp-model-studio\outputs\mlb-v18-current-state-pipeline-v1\slates\2026-09-10\sha256\edc583ee9e459720ee39e29aa9163b86c02ee68bf6a8e74bb683a788fe2e09fa\slate-result.json"
~~~

These objects contain the accepted Broadcast Replay path and full numerical simulation population, not newly generated Play Geometry/Population Geometry renderer supplements. No claim is made that all three AISP visualization tabs are enabled by this handoff.

## Repeated operation and ownership

Run in the intended Windows virtual environment:

~~~powershell
.\.venv\Scripts\python.exe scripts\acquire_mlb_v18_current_sources.py --start 2026-08-14 --current-pregame-source-exception --plan-only
.\.venv\Scripts\python.exe scripts\acquire_mlb_v18_current_sources.py --start 2026-08-14 --current-pregame-source-exception --allow-free-network
.\.venv\Scripts\python.exe scripts\run_mlb_v18_current_state.py
~~~

The exception flag is for newly acquired finalized current-input source history, not OOT evaluation. Planning is read-only. Acquisition requires the supported Windows approval/permission context; never weaken access controls after a rejection. Acquisition runs through yesterday Eastern, refreshes the three-completed-day correction window, and preserves original clocks when raw content is unchanged. Each invocation is bounded to 14 distinct catch-up dates and two concurrent public requests; remaining catch-up is explicit. No automatic retry loop or paid provider is used.

The runner selects the latest immutable acquisition attempt, including failures; --source-attempt <absolute-path> pins an attempt. It loads source/identity supplements, constructs required player windows, takes a fresh next-slate capture after ingestion and reuses unchanged numerical publications. --inventory <absolute-content-addressed-inventory-path> is diagnostic replay, not permission to backdate a forecast. Actual first-pitch checks run before and after inference. Complete input coverage still must pass the frozen transform.

Progress, source failures, per-game skips/failures and launch failures have preserved receipts. Rerunning reuses completed immutable sources and states; incomplete catch-up cannot become a cold-start claim. Earlier skips, network-permission failures, missing-hand diagnostics and superseded captures remain unchanged.

Owner: interactive Model Studio operator. No unattended scheduler or service was activated. Files, caches and publications survive closing Codex/restarting Windows; execution does not continue merely because files persist. The command now produces genuine current-game forecasts, but unattended nightly operation needs an explicitly assigned durable scheduler/process owner. Do not interfere with AISP services or describe this interactive run as unattended monitoring.

## Separate market composite

MLB_MARKET_COMPOSITE_HGB_V1 is unchanged. Registration: repository outputs/market-intelligence-rff-v1/candidate-registration/sha256/c5e7f6c2cae43fc4e330f7b3d16d3c12676f54114a581a3a75aecf757eb1020f/manifest.json. All three original fitted HGB/preprocessors, ordered contracts and five-row reload fixtures are byte-preserved and reproduce exactly. Same-40-game OOF log losses remain 0.650730337731732 composite, 0.661061445253144 nonlinear market control, and 0.701864919 raw consensus; they are not prospective evidence.

The future executable is exact saved fold 3, not a refit or fold ensemble; training cutoff September 3, 22:40Z. Status remains RESEARCH_CANDIDATE / PROSPECTIVE_VALIDATION_REQUIRED / NOT_PROMOTED, with no wagering authority. Its T60 contract requires timestamped canonical events, unstarted state, appropriately fresh full-game moneyline evidence from at least two books, and the original ordered signal recipe. No current composite record was fabricated or published.

Its learned disagreement input used Gen1, not V18; V18 cannot silently replace that input. Intended hierarchy: V18 PA model → V18 simulation → separately validated future game-level market layer → separately authorized persistent-regime specialists. Every new trained candidate must preserve its complete fitted estimator, fitted preprocessor, ordered feature contract, training cutoff and deterministic reload fixture; this does not authorize broad platform hardening.

## Focused verification and restrictions

Ten focused tests passed across seven files covering source/exposure, features, prospective transformation, simulation, publication and the frozen market artifact. A separate read-only current-identity checksum/canonical-map/cutoff check also passed. Accepted 32-row Development baseline reproduction is bitwise exact, maximum absolute prediction difference zero. Both actual games completed 5,000 legal simulations and exact paired 64-game replay. The earlier synthetic fixture is separate and not counted as a forecast. An actual same-inventory rerun reused both forecast objects, both feature snapshots and both game compositions, ran zero new inference, and retained the identical aggregate handoff descriptor. Existing AISP read-only verify_daily_slate validated both objects and the replay receipt; this was verification, not a live import. The normalizedSourceCache.reused flag is stale false inside the cached window payload and is not evidence against the separately verified numerical/evidence reuse. Checks cover authorized operational history, forged-capability rejection, unchanged sealed evaluation target guards, complete/sparse/cross-boundary windows, missing capture dates and immutable current-identity supplementation.

No broad suite, refits, calibration fitting, model selection, sealed Final OOT evaluation access, paid calls, AISP writes, promotion or wagering authority. Source restrictions remain LOCAL_PRIVATE_MODEL_DEVELOPMENT, attribution required, Statcast GOVERNED_LOCAL_RESEARCH_ONLY, no public raw redistribution and explicit commercial-rights review. Unrelated tracked/untracked work is preserved.
