# ASP Model Studio and AISP — project-management handoff

Prepared for James and a replacement project-management AI on September 11, 2026. Code, artifact metadata and local runtime observations were inspected around 21:07–21:13 UTC (17:07–17:13 Eastern). This is a technical status report, not authorization for a new study, provider purchase, model promotion or deployment.

## 1. Executive summary

ASP Model Studio is the upstream model-development, scientific-evidence and simulation workbench for the AI Sports Predictor ecosystem. AISP is the operational/product application: it collects current evidence, presents forecasts and simulations, applies separately governed decision rules, and maintains virtual-position and settlement ledgers. Model Exchange is the file-based, versioned integration boundary between them.

The main objective is to turn attributable sports data into reproducible, timely probabilistic forecasts and simulations whose limitations are visible, then measure their prospective performance without contaminating development or silently granting betting authority. More models, more forecasts or more displayed charts are not substitutes for that objective.

The project is well beyond a prototype with no executable model. The frozen MLB V18 model runs on genuinely current pregame inputs. At the specifically inspected September 11 publication receipt, **eight of fifteen games had V18 base forecasts**, each with 5,000 completed simulations. All eight had creation timestamps before scheduled first pitch, and all 32 bound base child files passed SHA-256/byte-count checks during this report. The other seven dispositions were `CHECKPOINT_NOT_DUE` in that particular receipt, not seven terminal source failures.

However, there are important distinctions:

- V18 is registered in Model Studio as James's **conditional operational MLB forecasting champion**, with `historical_validation_under_review`. This is not a claim of clean historical validation or wagering superiority.
- The published forecast objects retain their original research-only provenance. AISP model-era/decision authority is a separate supplement and state transition.
- AISP now contains automatic V18 import and conditional-champion activation code. This report did not query its live activation/import database state, so code capability is not reported as completed live activation.
- The current-state publisher/exporter and the older daily geometry publisher are not fully equivalent: **the current-state exchange explicitly rejects Play/Population Geometry supplements**. Eight base forecasts do not establish eight complete three-view simulator publications.
- The frozen V18-plus-HGB starter-duration comparison is a separate prospective research pilot. One COL–DET pair is published, frozen and awaiting a final; no pair has been scored at this snapshot.
- NFL development is paused with M1 retained. The NBA intake pilot is access/rights blocked on an isolated branch. Neither should displace the immediate MLB operational and prospective-measurement work.

## 2. The three systems and their purpose

| System | Location | Primary responsibility | What it must not silently do |
| --- | --- | --- | --- |
| ASP Model Studio | `C:\Users\james\asp-model-studio` | Data and identity contracts; feature engineering and treatment; training and evaluation; fitted-artifact preservation; simulation; current-input construction; precomputed forecast publication | Change AISP policy/positions; treat a research result as promotion; manufacture missing observations |
| AI Sports Predictor / AISP | `C:\Users\james\ai-sports-predictor` | Current event/participant observations; legacy Gen1 operations; forecast import and product display; prices; readiness and decision policy; virtual experiments, positions and settlements | Execute arbitrary imported estimators; reinterpret artifact authority; backdate forecasts or overwrite prior model eras |
| ASP Model Exchange | `C:\Users\james\asp-model-exchange` | Versioned manifests, immutable packages, identity bridges, forecast/simulation supplements and consumer handoffs | Become an unrestricted shared mutable database or an implicit authority to trade |

In practical terms, Model Studio is the research and forecast-production workshop; AISP is the operational application and measurement environment. They are separate repositories and applications, not two screens backed by one database.

The long-term product goal is a reliable multisport probabilistic forecasting and simulation platform. It should explain what evidence was available, how the forecast was constructed, what uncertainty remains, and why a proposed opportunity is qualified or rejected. Event forecasts, decision policies and capital allocation are different layers. A good game forecast can still produce no position because prices, readiness, timing, edge or staking requirements fail. The immediate platform remains local/private research and virtual accounting; this report establishes neither a real-money execution capability nor a public-production readiness certificate.

## 3. Construction: software architecture

### Frontend and API

Model Studio uses React 18, TypeScript, Vite, React Router and Zustand. Its application entry chain is `src/main.tsx` → `src/AtlasApp.tsx` → `src/apps/ModelingApp.tsx`. The `Atlas` names reflect the inherited workbench foundation, not a separate currently authoritative sports model.

The Python backend is FastAPI, with Pydantic request/response contracts and routes mounted under `/api`. The current project-bound sports Stage 3 endpoints are implemented in `server/persistence/persistence_router.py`. They resolve the active project, dataset and registered authorities rather than accepting an unscoped model execution request.

The PA cockpit exposes fifteen workflow steps: Objective, Population, Profile, Outliers, Missing, Feature Engineering, Segmentation, Split/Balance, Model Development, Candidate Evaluation, Refinement, Calibration, Game Evaluation, Champion/Challenger Decision, and Registry/Export. These are a workflow map, not proof that every screen is equally complete. For example, current-Gold Player Segmentation still has a later-step gate; several completed research studies are script/artifact workflows rather than generalized interactive UI features.

Authentication is enabled by the local launcher; public registration is disabled. Project view/edit authorization and user/project-bound persistence are separate from scientific eligibility gates. Browser login does not grant model promotion, source rights or OOT access.

### Persistence and artifacts

Model Studio uses its own SQLite persistence and separate security database under `.runtime/asp-model-studio/`. Repositories and migrations maintain project, dataset, treatment, feature-set, split, run, registry and evidence records. SQLite foreign keys, WAL, busy timeout and transactional migrations support local durability.

Scientific payloads are not simply rows in that database. Large data, fitted models, predictions, execution inputs, manifests and receipts live in filesystem artifact stores. The main categories are:

- `.runtime/asp-model-studio/`: local application state, jobs, runtime configuration, logs and working artifacts;
- `server/artifacts/`: governed model/data authority objects, including the permanent quarantine ledger;
- `outputs/<versioned-workstream>/`: immutable research and publication objects plus current locator files;
- `.deployments/mlb-v18-unattended/<commit>/`: pinned executable publisher releases;
- the external Model Exchange: copies/packages for consumers.

A mutable `CURRENT.json`, `current.json` or `latest.json` is a locator. It is not the scientific identity of its target. Authoritative objects have immutable versions and hashes; new evidence creates a successor rather than replacing bytes inside an existing content address.

Generic uploaded-data workflows also maintain scoped in-memory DataFrames/results with backend-owned checkpoints. This is distinct from the immutable sports evidence pipeline. A test or secondary tool must not overwrite the live backend checkpoint.

### Computation and job ownership

The numerical stack includes NumPy, pandas, SciPy, scikit-learn, XGBoost and other supported model libraries; Arrow/Parquet are used for structured data. Dependency manifests describe intended dependencies, while the relevant fitted artifact and execution receipts establish the environment actually used. Not every library present in the repository is an approved model in the current program.

Stage 3 jobs use a process-local coordinator, an interprocess lock and resource-aware scheduling. Native-worker limits and exclusive large-model runs prevent nested oversubscription. Progress records, scheduled fit slots, actual estimator starts, completed folds and immutable completion receipts are different facts. An API restart does not preserve a running Python fit: orphan reconciliation retains completed evidence and records interruption rather than pretending all unstarted work resumed.

Sources: [application shell](C:/Users/james/asp-model-studio/src/apps/ModelingApp.tsx), [PA cockpit](C:/Users/james/asp-model-studio/src/sports/cockpit/PaModelingCockpit.tsx), [API](C:/Users/james/asp-model-studio/server/main.py), [Stage 3 routes](C:/Users/james/asp-model-studio/server/persistence/persistence_router.py), [job coordinator](C:/Users/james/asp-model-studio/server/sports_current_statcast/stage3_model_jobs.py), [local launcher](C:/Users/james/asp-model-studio/scripts/start-asp-model-studio.ps1).

## 4. How data becomes a model

The implemented scientific sequence is source evidence → identity reconciliation → analytical datasets → feature treatment and sufficient statistics → chronological fitting/evaluation → frozen executable artifacts → pregame simulation/publication.

### Source and identity layer

Source registrations carry dataset/version identity, physical schema, source-use restrictions, checksums and availability metadata. Historical MLB foundations include the FD1/Lahman exchange, Retrosheet-derived evidence, and Statcast/MLB source evidence under their applicable authorities. NFL uses its own separately governed sources and contracts.

Canonical identities connect provider IDs, model identifiers and AISP UUIDs for games, teams and players. A name match is not enough. Wrong opponent orientation, unresolved aliases, doubleheaders and suspended/resumed games can invalidate an otherwise plausible feature row.

Bronze preserves original evidence; Silver normalizes identities and events; Gold materializes analytical player, PA and context features. This is not yet a single completely generalized multisport data platform: several authorities and publication paths are sport- and experiment-specific.

### Time and information availability

The platform must distinguish event time, completion time, provider update time when known, observation time, availability time, ingestion/capture time, forecast creation time and decision cutoff. Downloading historical data today does not establish that it was available before an old game. Republishing an unchanged artifact today does not refresh its source evidence.

Pregame composition uses the specific game's evidenced participants, ordered lineups, starter observations and source histories. Historical lineups and model predictions cannot stand in for absent current observations. Open-window missing evidence is pending; a closed deadline is a terminal no-backfill condition.

### Feature treatment and priors

The treatment system distinguishes observed zero, structural zero, true cold start, insufficient exposure, unavailable evidence, invalid values and held scientific states. These distinctions matter particularly for last-100-PA and last-250-BF statistics. Missing source coverage cannot be turned into zero prior starts or solved by an unapproved generic median.

Twenty-one governed prior paths are available across the accepted MLB treatment. Method families include Beta-Binomial/two-cell shrinkage, Dirichlet-Multinomial composition shrinkage, Gamma-Poisson component shrinkage and Normal-Normal shrinkage. Parameters are learned from training-only authority, then frozen for validation or prospective transformation. Publishing component counts alone does not mean an estimator has been implemented or fitted.

Pitch composition includes the other/unclassified category so the full composition reconciles with all pitches. Event/exposure counts retain integer types; velocity sum and sum-of-squares retain floating-point precision. Derived interactions are recomputed after parent treatments, not reused from incompatible raw parents.

Three fields remain retired by scientific decision, with history retained: `pitcher_era9`, `batter_obp`, and `batter_last100_contact_rate`. Retired is not the same status as unresolved missing evidence.

Sources: [dataset consumer](C:/Users/james/asp-model-studio/server/sports_datasets/consumer.py), [current input inventory](C:/Users/james/asp-model-studio/scripts/inventory_mlb_current_slate.py), [Wave 2 priors](C:/Users/james/asp-model-studio/docs/MLB_PLAYER_STATE_PRIOR_WAVE2_IMPLEMENTATION_REPORT.md), [interaction authority](C:/Users/james/asp-model-studio/docs/MLB_INTERACTION_RECOMPUTATION_AUTHORITY_V1_IMPLEMENTATION_REPORT.md).

## 5. What MLB V18 actually is

V18 is an executable plate-appearance probability model coupled to a baseball state-transition/game simulator. It is not merely a direct home-win classifier, and it is not the later HGB starter-duration model.

| Binding | Current frozen identity or meaning |
| --- | --- |
| PA estimator | `MLB_V18_HGB_PA`, histogram gradient boosting, accepted fold 5 |
| PA artifact SHA-256 | `44ec4f457741f1aaeff42b81af1be5fd2712e494709ff1a0a8f0742b88d71c8b` |
| Accepted parent bundle | `a6e7e99122f1b60701a4728b97b32fcc11e03405bfd456ed6cd54f69b69adb27` |
| Treatment specification | `stage3-feature-treatment-spec-711fbb376e9a4d419f826de593195638` |
| Treatment manifest | `4d158e01a4a7d84fe6e7641f61edf0e9848f1775e025a2cec6c29cda22d479f3` |
| Input dimensions | 246 raw source-contract fields → 273 treated inputs → 436 encoded columns for fold 5 |
| Transition dependency | Accepted transition fold 4; SHA `0e5e480f897ddefa5f9dddbc229a8a43bf29f7b81443c25ece611d9d4032b253` |
| Calibration | Identity / `RETAIN_RAW_V18`; unselected temperature alternative is not applied |
| Studio registry version | `mv-mlb-v18-conditional-3e8dcc1c50dcdfd2d748e5e0` |

The exact eight-class order is `STRIKEOUT`, `WALK_HBP_CI`, `HOME_RUN`, `SINGLE`, `DOUBLE`, `TRIPLE`, `BIP_OUT`, `OTHER_REACH`. Walk/HBP/catcher interference remain combined; `OTHER_REACH` remains separate. Changing this mapping would create a different target/model, not a harmless cleanup.

The operational fold-5 estimator trained on 582,342 eligible PAs in 7,728 games, nominally March 30, 2023–May 1, 2026. It is **not** a newly fitted all-Development estimator. Registered Development has 683,662 PAs through August 13, 2026; the unchanged 56-observation eligibility hold leaves 683,606 eligible. The five validation windows have 501,539 common eligible observations after the 51 validation-window holds. **2025 is Development for V18.** Older code/comments describing all of 2025 as sealed belong to earlier authorities.

The current raw246 composition spans annual player priors; PA/pitch rolling history and exposure; team, schedule and venue context; calendar; participant handedness; simulated PA state; and canonical metadata. The first successfully repaired current-source games had 34 supported templates each: eighteen starting-lineup matchups and sixteen active-pitching-staff templates. That count is not a claim that every future game uses exactly those same participants or has automatic coverage.

Each PA probability vector feeds the frozen transition/game mechanics: base/out state, scoring, inning changes, batting order, starter removal and the accepted relief-template mixture. A standard publication saves 5,000 complete game simulations and derives win probabilities, expected home/away runs, margin/total distributions and representative paths. A legal simulation and exact reload establish implementation consistency; neither proves calibration or predictive superiority.

The reliever mechanism is an anonymous staff-template mixture, not a complete player-specific bullpen availability/exhaustion model. Geometry is renderer-ready simulated geometry, not measured Statcast tracking or invented physical truth.

Complete **contract support** is also not complete current-world knowledge. The saved September 10 two-game feature-quality audit classified the 246 fields as 176 complete for their precise definitions, 31 partial/recovery proxies, 25 historical annual fields by design and fourteen numerical-missing families represented by truthful missingness flags, with zero unsupported contract fields. Those flags do not create missing weather, bullpen or other observations. This two-game breakdown was not independently repeated for the eight September 11 games. Catcher effects, actual roof state, umpire, injury/return information, MiLB translations and individual reliever availability are not all incorporated merely because a forecast passes its frozen contract. [Feature-quality qualification](C:/Users/james/asp-model-studio/docs/MLB_V19_CURRENT_FEATURE_QUALITY.md).

Sources: [conditional champion and exact bindings](C:/Users/james/asp-model-studio/docs/MLB_V18_CONDITIONAL_CHAMPION_HANDOFF_V1.md), [current-state construction](C:/Users/james/asp-model-studio/docs/MLB_V18_CURRENT_STATE_PIPELINE_V1.md).

## 6. Scientific status: what is established and what is not

The corrected V18 recovery completed its five authorized fits and preserved the actual fitted preprocessing, estimator, predictions and reload evidence. On the saved matched Development population, historical log loss was 1.47458954 for V18 versus 1.47455830 for V14; the difference was about +0.00003124. The reported game-clustered interval included zero. This did not demonstrate superiority, and the cold/no-history subgroup results raised additional qualification concerns.

More importantly, subsequent source-timing work found historical completion/availability problems. For example, part of `BOS202406260` occurred after the fold-2 training cutoff: at least 55 of 70 PAs are proven later labels, and conservative whole-game quarantine is required for that diagnostic. Other rolling histories have potential ordering/availability exposure, and some 2026 completion authority is incomplete. A source-date sort is not enough to prove historical point-in-time validity.

Accordingly, those stored numerical comparisons remain preserved historical research observations, **not clean estimates of prospective performance**. Exact reproduction does not cure leakage. The bounded completion diagnostic did not reconstruct a certified clean five-fold comparison. James subsequently selected the frozen V18 model for conditional prospective operation while retaining the historical-validation warning; the decision did not retroactively validate the historical results.

The V19 challenger study was stopped. The older V18/RF ensemble is also non-operational: the original RF fitted estimator could not be recovered, and a replacement RF is not authorized. Saved predictions are useful research evidence but cannot substitute for an executable original model. Neither study should be reopened merely because a new project-management chat starts.

The prospective acceptance supplement keeps early/daily reports descriptive. Its two formal looks are at 250 and 500 paired games with fixed alpha allocation and a minimum of eight ISO-week blocks. The +0.020 log-loss noninferiority margin remains proposed, not approved; automatic noninferiority advancement is disabled. Those rules must not be confused with authorization to promote the current one-game duration pilot.

Sources: [corrected recovery](C:/Users/james/asp-model-studio/docs/MLB_CORRECTED_HGB_RECOVERY_1.md), [historical timing limitation](C:/Users/james/asp-model-studio/docs/MLB_V18_CONDITIONAL_CHAMPION_HANDOFF_V1.md), [RF operationalization](C:/Users/james/asp-model-studio/docs/MLB_V18_RF_OPERATIONALIZATION_V1.md), [prospective protocol V2](C:/Users/james/asp-model-studio/docs/MLB_V18_ACCEPTANCE_PROTOCOL_V2_AND_GEN1_BET_READINESS.md).

## 7. Current MLB publication: fresh operational evidence

The September 10 current-source repair produced legitimate pregame COL–NYY and PIT–CWS forecasts. That replaced the earlier condition in which Studio could only see expired September 8 evidence. The repair connected current canonical participants and source-backed annual/rolling/context inputs to the frozen V18 preprocessor and estimator; it did not retrain V18.

The independently inspected September 11 aggregate, generated at **21:07:21 UTC**, contains eight base forecasts:

| Game | Forecast creation before scheduled first pitch |
| --- | ---: |
| PIT–CHC | 96.97 minutes |
| COL–DET | 168.96 minutes |
| LAA–WSH | 165.19 minutes |
| NYM–NYY | 165.11 minutes |
| KC–BOS | 223.37 minutes |
| PHI–ATL | 165.31 minutes |
| CIN–MIL | 157.71 minutes |
| CWS–STL | 213.89 minutes |

All eight report 5,000 simulations and zero illegal states/nonterminations. Their retained receipts report a 64-simulation deterministic replay; this report did not rerun that replay. This report independently checked the eight capture ≤ creation < start timestamp orderings and the 32 bound base child-file checksums/lengths.

The receipt says one forecast was newly completed during that invocation and eight were included in the aggregate. These are not eight new fits or eight new forecasts on every tick. Seven other games were marked `CHECKPOINT_NOT_DUE`; consult their last substantive readiness evidence before describing their missing inputs or final disposition.

Exact local handoff:

`C:\Users\james\asp-model-studio\outputs\mlb-v18-current-state-pipeline-v1\handoffs\sha256\1006bc2226ce703072d1a87736fe504b1584244c23fae0fe3f5b20b9f412a624\aisp-handoff.json`

- Logical handoff identity: `1006bc2226ce703072d1a87736fe504b1584244c23fae0fe3f5b20b9f412a624`.
- Physical file SHA-256: `ecb8f1b758f2fdf770ca6f25c12ce1906ad9a59b4e9fcbea4370dbe65c3b951e`; 124,899 bytes.
- Associated receipt identity: `ec95f6e6769ab2af372091878ccc0507c4713cfcb2b78064f7f9d580b42cfe84`.

Logical identity hashes and physical serialized-file hashes can differ by contract. Do not substitute one for the other during import verification. This is a fixed as-of snapshot; the independent publisher can advance later locators while this report remains unchanged.

### Concrete visualization integration gap

The older daily publisher has accepted Play Geometry and Population Geometry implementations: complete representative PA paths, supported contact traces, anonymous runner movements, 5,000-game population summaries, 100 accumulation frames and six representative games.

The newer current-state/unattended path does not presently generate and export those supplements through the same complete route. `mlb_v18_exchange.py` requires the four base children and explicitly raises `V18_EXCHANGE_VIEW_SUPPLEMENT_EXPORT_NOT_SUPPORTED` if Play/Population Geometry references are present. Conditional schema handling in current publication is not geometry generation.

Therefore current numerical publication is implemented, but current-slate three-view parity is a remaining integration task. The existing schemas/renderers should be reused; the appropriate repair is not another visualization format or a different model. No browser three-view verification was performed for these eight games in this report.

Sources: [fixed receipt](C:/Users/james/asp-model-studio/outputs/mlb-v18-current-state-pipeline-v1/slates/2026-09-11/sha256/ec95f6e6769ab2af372091878ccc0507c4713cfcb2b78064f7f9d580b42cfe84/slate-result.json), [exchange exporter](C:/Users/james/asp-model-studio/server/sports_current_statcast/mlb_v18_exchange.py), [older daily views](C:/Users/james/asp-model-studio/server/sports_current_statcast/mlb_v18_daily_views.py).

## 8. How data passes between AISP and Model Studio

Integration is bidirectional by data type, but each specific transfer has a producer, consumer and contract. It is not unrestricted two-way mutation.

### AISP to Studio: historical data and current inputs

Historical MLB data is delivered through versioned FD1 manifests and an identity bridge in `asp-model-exchange/datasets/mlb-fd1` and `identity-bridges/mlb-fd1`. Studio validates schemas, source rights, partitions, hashes and identity authority before consumption.

Current MLB evidence also uses a deliberately scoped local read-only database interface. `inventory_mlb_current_slate.py` captures AISP's upcoming games and current observations under `AISP_MLB_READ_ONLY_PREGAME_SNAPSHOT_V2`, using a read-only repeatable-read transaction. It retains canonical/external identities, schedule and venue, current starter/lineup observations, source clocks/checksums and relevant roster/context metadata. Its pregame queries exclude outcomes and markets. Existing Gen1 forecast metadata may be inspected for reconciliation; its probabilities are not substituted for V18 source inputs.

Studio combines that capture with its independently retained and permitted historical sources to construct the exact frozen input contract. Reading AISP's database through this authorized bridge does not mean the two applications share an application database or that Studio may write to AISP.

### Studio to AISP: forecast packages

For current V18, Studio creates immutable per-game objects and an aggregate handoff/receipt. The current base object contains `forecast.json`, `pregame-evidence.json`, `execution-inputs.json`, `representative-path.json`, and manifest bindings; the feature snapshot is referenced and copied through the package contract.

The exporter validates child-path containment, hashes/lengths, identities, research flags, full-slate accounting and timestamps. It stages and atomically publishes the package in:

`C:\Users\james\asp-model-exchange\mlb-v18-current\sha256\<packageSHA>\exchange-package.json`

Unchanged numerical input/model/seed identity reuses an existing forecast. New observation or publication timestamps alone do not warrant new numerical evidence. Accounting-only packages with zero forecasts remain explicit accounting and must not be passed to an importer that requires forecasts. The current geometry limitation described above applies to this exporter.

AISP's `jobs/v18_exchange_consumer.py` discovers these packages, verifies them and delegates to the same daily importer used by the CLI. Bundles are persisted in `shadow_forecast_bundles`; forecasts in `shadow_forecasts`. Handoff SHA deduplicates bundles, and `mlb-v18-daily-<objectSHA>` identifies numerical forecasts. Exact repeat import reuses records; conflicting content fails closed.

The automatic V18 import switch is `MLB_V18_EXCHANGE_AUTO_IMPORT_ENABLED`, separate from broader/NFL `MODEL_EXCHANGE_AUTO_IMPORT_ENABLED`. Code defaults are not evidence of configured live values. A supported manual import uses AISP's Python/server environment with `python -m scripts.mlb_v18_daily_slate import --handoff <verified copied handoff> --receipt <verified copied receipt>`. The copied package's import instructions and hashes must be used, not guessed paths.

### Forecast import is not authority import

AISP now implements `v18_champion.py` and `v18_forecast_view.py`. A separate hash-verified conditional-champion supplement can arm a future model-era boundary and become active only at that boundary. It preserves predecessor decisions, open liabilities and existing policy/staking settings. The saved V18 forecast is adapted into the decision interface without executing its estimator in AISP. Missing required V18 evidence yields an explicit skip, not silent Gen1 fallback in an activated V18 era.

The Studio handoff proposed September 12 midnight Eastern (`2026-09-12T04:00:00Z`) as a future boundary. **Whether Claude has imported/armed that authority in the live AISP database is not established by this report.** If the boundary is missed, the supported answer is a new immutable future-boundary supplement, never backdating or retrospective positions. Forecasting-only operation is safer than inventing an unreconciled capital transfer.

The four distinct states are: **produced in Studio → imported in AISP → authorized in a model era → qualified by decision policy**. Each needs its own evidence. A visible forecast, an importer success, an activated era and a virtual position are not interchangeable.

### Other transfer directions and exceptions

NFL forecasts use their own current/history index at `aisp-daily-forecast-bundles/nfl-2026-research-shadow-index.json`. NFL Labs supplements have separate namespaces. AISP can, under its configured frozen NFL orchestration, launch a Model Studio producer subprocess and then import the result. The imported-estimator consumer still does not execute the estimator itself. Thus “AISP never initiates computation” would be too broad; “Model Studio owns the imported models' numerical execution” is the intended boundary.

Legacy Gen1 MLB forecasts also have an AISP-native producer (`asp_mlb_ensemble`, historically `2.0.0-gate2-08cca634c81b`). Do not assume every forecast visible in AISP originated in Model Studio or is V18. Model/version and era must be inspected.

For prospective measurement, Studio can read a persisted, provenance-bearing AISP final after the final-status gate. Both arms use the same final revision. This is a restricted results-intake path, not permission to read live outcomes early or to change settlements.

Sources: [current-input capture](C:/Users/james/asp-model-studio/scripts/inventory_mlb_current_slate.py), [V18 consumer](C:/Users/james/ai-sports-predictor/server/app/jobs/v18_exchange_consumer.py), [daily importer](C:/Users/james/ai-sports-predictor/server/app/shadow_import/mlb_v18_daily.py), [authority service](C:/Users/james/ai-sports-predictor/server/app/services/v18_champion.py), [forecast adapter](C:/Users/james/ai-sports-predictor/server/app/services/v18_forecast_view.py).

## 9. Immediate active experiment: frozen starter-duration pairs

The current assignment is prospective measurement of the accepted V18 reference against the same frozen V18 PA/game system with an HGB starter-duration adapter. It is not another model-family search, PA-target redesign or policy study.

The HGB duration component has its own historical study and fitted artifact. Historical component improvements do not establish whole-game improvement. The current controlled comparison preserves all shared forecast inputs and mechanisms, changing the declared duration adapter. Changed stopping times can alter subsequent simulated paths; one realized game cannot identify causal managerial value or establish general superiority.

The duration artifact SHA is `f64f82b4fadf35acd3418bc298548c48bb73cf624fe8c70ba01a87c33e8d2370`. Its historical held-out component study covered 2,302 starts / 1,162 games: BF CRPS 2.0310 versus empirical 2.2533, expected-BF MAE 2.8541 versus 3.0794, and 90% interval coverage 91.09%. These are duration-component results, not full-game winner/margin improvements. The lossless hierarchical PA implementation also exists, but real A/B/C comparison fits remain zero because a timing-valid common feature history was not certified. The broader PA-history study is deferred. [Component study and withheld PA work](C:/Users/james/asp-model-studio/docs/MLB_STARTER_SURVIVAL_HIERARCHY_RESULTS_V1.md).

Complete starter histories were reconciled for Framber Valdez and Mason Adams: 121 candidate starts accounted for as 119 eligible and two justified exclusions, with zero unresolved starts in those scoped histories. These are two completed pitcher histories, not a claim of complete starter histories for the entire league. The 2025–2026 portion contains 62 eligible starts. Missing coverage for other pitchers remains a real publication dependency.

The retained bounded intake accounting is 60 source requests, 23,363,290 bytes and $0, against the separately authorized cumulative ceiling of 200 requests / 500 MiB. The current cached readiness task does not grant fresh acquisition authority beyond its saved scope.

The COL–DET pair is `mlb-duration-pair-51de2e1e0481f6165a43459f`, game UUID `7323d8f3-9b24-464d-903e-fe290913d73b`, MLBAM `824227`. It was published at 20:09:47.587959 UTC before its 22:35 deadline. Each arm has 5,000 frozen draws. Pair SHA is `fdee9e2fa72c8339c9bbd0d9e723d8898c34c80671c44eaf1d1f843674edfd45`.

At the latest paired-monitor snapshot: 15 games accounted for, one expired unpublished, thirteen pending, one pair published, one awaiting a final and zero scored. The last completed all-game pair-readiness pass was 20:09:48 UTC; later attempts deferred to the production publisher. The eight regular V18 base forecasts and the one duration pair are different populations with different input requirements.

Once a legitimate persisted final arrives, separate arm reports cover winner log loss/Brier; home/away runs, margin and total errors; marginal CRPS, joint energy score and interval coverage; and Adams/Valdez predicted BF versus actual BF where exact final-linked starter evidence exists. A final team score alone does not establish starter BF. Unsupported actual BF remains explicit rather than inferred from team PA. Scores and any corrections are immutable, paired to the same final revision and never used here for fitting, tuning or selection.

The pair handoff is `C:\Users\james\asp-model-exchange\mlb-starter-duration-research-v1\current.json`; index SHA `2eed387ab4f9b14747a1fc9fc09fa944ec14e3bb46c649346d25b8a35d296c32`. It remains separate research-only evidence. No dedicated paired-duration importer was found in the bounded AISP import/service inspection; do not claim the pair is displayed or imported simply because the exchange exists.

Sources: [prospective exception and published pair](C:/Users/james/asp-model-studio/docs/MLB_STARTER_DURATION_PROSPECTIVE_EXCEPTION_V1.md), [monitor handoff](C:/Users/james/asp-model-studio/docs/MLB_STARTER_DURATION_MONITOR_HANDOFF_V1.md), [final-gated scorer](C:/Users/james/asp-model-studio/server/sports_current_statcast/mlb_starter_duration_paired_scoring.py).

## 10. Operational ownership and current local runtime

There are three different kinds of execution, with different persistence guarantees:

| Owner | What it runs | Current status / limitation |
| --- | --- | --- |
| Model Studio API process | Interactive workbench and Stage 3 coordinators | Configured UI/API ports 5274/8101 were not observed listening during this report; no service was started or changed |
| Windows Task Scheduler | `ASP MLB V18 Research Publisher` | Installed independent publisher, pinned release `9bb1a947fc863596433fac569822ad95f2c71dac`; last observed run 21:07:07 UTC, result 0, next 21:12:12 UTC |
| Codex heartbeat tasks | Temporary MLB pair readiness/final scoring and ordinary NFL evidence archive | MLB five-minute task ACTIVE; NFL six-hour archive PAUSED under the authorized temporary handoff |

The Windows publisher uses the repository's `.venv` and a fixed `.deployments` code snapshot, not whichever branch happens to be checked out. It has ownership/hash checks, a STOP switch, overlap/process locks and bounded work. Closing Codex does not change the Windows-owned task. Reboot/startup operation is configured; a forced restart test was not performed for this report. Task exit code zero is not proof every source is fresh or every game was forecast—the substantive receipts determine that.

AISP was observed listening at frontend 5173 and backend 8010, not the older 8018 port. Port observation is not a full health, authentication or data-freshness test. The Model Studio web application being down does not mean its independent publisher is stopped.

NFL was paused at **September 11 20:52:51.349 UTC**. Its exact prior configuration, cursor, evidence identities and next-run information were preserved. MLB pair monitoring activated at 20:57:47.720 UTC. Restore NFL once all currently published pairs are scored, or by **September 12 20:52:51.349 UTC**, whichever comes first. Restoration must verify the actual task state and an actual run of the original archive, not only configuration intent. At this snapshot restoration is pending, not completed.

The heartbeat tasks require the desktop application running and the computer available. If unavailable at expiry, overdue restoration is the first action on the next wake; this is not an OS-independent 24-hour guarantee. This distinction was checked using OpenAI Docs and the task's own saved protocol. [Official scheduled-task requirements](https://learn.chatgpt.com/docs/automations?surface=app).

Starting a new project-management chat does not migrate these existing task owners or recreate their preserved state. Leave the existing monitor and restoration receipts intact; the new manager should coordinate with them rather than install duplicate loops. The Windows publisher is separately pinned and must not be confused with either heartbeat.

Source: [Windows owner design](C:/Users/james/asp-model-studio/docs/MLB_V18_SCHEDULER_OWNERSHIP.md), [actual recent publisher evidence](C:/Users/james/asp-model-studio/docs/MLB_V18_CONDITIONAL_CHAMPION_HANDOFF_V1.md), [temporary switch receipts](C:/Users/james/asp-model-studio/outputs/mlb-starter-duration-paired-research-v1/monitoring/current.json).

## 11. Other workstreams and their disposition

### NFL

The existing `NFL_M1_XGBOOST` track is retained; row volume is not evidence of current inputs or prospective validity. Its frozen current-input publisher and immutable bundle mechanism exist. The retained version is `NFL_M1_2026_RESEARCH_SHADOW_V1`, with binary SHA `7bec06646fd5035380107501d07e139425ac483a47e02e0bbbd56301124fb8fd` and training cutoff February 8, 2026. Evidence freshness is separate from publication time: a saved September 9 freshness receipt identifies August 29 at 14:07:34.968754 UTC as source-as-of and explicitly reuses unchanged numerical evidence. This is a dated observation, not a new claim that every current NFL package still has exactly that snapshot. [Saved M1 freshness handoff](C:/Users/james/asp-model-studio/outputs/nfl-existing-track-current-shadow-v1/sha256/9c8bdefa6c074e1dbb0557b679609565640c68ac029e99b57a833bd5505b7641/handoff.json).

The current-state/cold-start V2 work and its narrow uncertainty repair are completed research. The repair removed six uncertainty-only fields from score means after tracing a 14.130862-point current home-margin distortion. Legitimate exposure/state features remain; uncertainty adjustments were fitted from Development evidence rather than an arbitrary score offset. The repaired mean contract has 52 inputs.

On the saved 1,408 matched Development games, the primary repaired residual system's raw log-loss difference versus M1 was +0.0047, with an exploratory interval spanning zero. An equivalent chronological calibrated comparison also spanned zero. Correctness did not establish superiority, and no raw/calibrated winner was selected. These historical inputs are retrospectively reconstructed availability approximations, not complete archived publication vintages. Supplemental current roster/depth evidence must not be described as numerical team-strength updates when the frozen model does not consume it. M1 remains retained and NFL expansion is stopped.

Source: [NFL repaired research report](C:/Users/james/asp-model-studio/outputs/nfl-current-state-cold-start-v2/uncertainty-repair-v1/reports/sha256/1d8a9129853f68c87873e6cfbabc93a11450a80bcd09fb9bab968db238af0ba3/research-report.md).

### NBA

The data pilot is paused for entitlement/rights clarification, on isolated branch `codex/nba-sportsdataio-pilot-v1`, commit `da05d9f6f12ecb628101dab42f67709101d01265`. Verdict: `NBA_REAL_DATA_PILOT_ACCESS_BLOCKED`. It is not an operational NBA model or simulator. Zero account requests, zero basketball payload bytes and zero real acquired/reconciled games were reported; synthetic parser checks are not a real-data pilot.

Immutable offline intake and conservative reconciliation were implemented, but full five-player stint/minute reconstruction and possession segmentation remain unimplemented. Existing-account NBA entitlement, $0 real-data access and intended training/archive/display rights must be established before acquisition. The prior pilot cap remains three completed games / 25,000,000 original bytes, with no trial activation, provider contact or purchase implied by this handoff.

On that isolated branch, `docs/nba-sportsdataio-pilot-v1/PILOT_REPORT.md` contains the findings and `docs/nba-sportsdataio-pilot-v1/SPORTSDATAIO_INQUIRY.md` contains the ready-to-send, unsent inquiry. Those files are not assumed to exist in the current checkout. James must send the inquiry or provide written entitlement/cost/rights confirmation; switching the active MLB checkout is not required to read the saved branch documents.

### Market intelligence, readiness and selection policy

Market/RFF work is a separately bounded research laboratory. Market observation and time-safe feature contracts are not a promoted predictive or betting model. The completed MLB selection-policy study ended with `MLB_STRICT_POLICY_RETAINED`: retain the existing V2.1 decision rules and 2% threshold; do not reactivate historical V1 or optimize thresholds in response to these new outcomes.

The saved market study's comparative OOF evidence contained only forty games across seven dates/two ISO weeks. Its required longer-block support was absent; the formal 28-day-block requirement had only one block available. All 775 RFF checkpoints across 152 games were labeled `PROVISIONAL_RFF`, with sparse component coverage. Unavailable evidence is not low risk. No policy or wagering authority follows from its exploratory metrics.

Readiness, price availability, quote staleness, valid pregame forecasts, lineups/starters and edge/EV checks explain different kinds of rejection. Repeated policy decisions are not independent games. Counterfactual profitability for a rejected bet requires a legitimate contemporaneous quote and eventual outcome; it cannot be inferred from outcome alone. Missing sportsbook data remains a limitation. Forecast improvement and decision-policy evaluation should remain distinct projects.

Source: [market/RFF report](C:/Users/james/asp-model-studio/docs/MARKET_INTELLIGENCE_RFF_RESEARCH_REPORT_V1.md), [readiness cohort and protocol separation](C:/Users/james/asp-model-studio/docs/MLB_V18_ACCEPTANCE_PROTOCOL_V2_AND_GEN1_BET_READINESS.md).

## 12. Permanent scientific and operational boundaries

The true V18 Final OOT period is August 14–27, 2026. Its remaining evaluation payload is sealed. Three whole games were permanently quarantined under James's narrowly scoped source-history exception:

| MLBAM game | Canonical model game | Authorized source appearance |
| --- | --- | --- |
| 823343 | `game-3580e8be4936befc32ff752d` | Framber Valdez, August 17 |
| 824235 | `game-a0765f54db9c74c24161785f` | Framber Valdez, August 24 |
| 822693 | `game-e53ecedc71413e735ca59695` | Mason Adams, August 25 |

Reason: `PROSPECTIVE_FEATURE_CONSTRUCTION`. Identity-only accounting permanently removes 230 of the original 14,067 observations, leaving **13,837** in the remaining sealed cohort. Those are key counts, not authorized evaluation results. Any future OOT comparison, calibration decision, component evaluation or promotion claim must apply the whole-game quarantine before loading outcomes and disclose the reduced cohort. Changing pitcher, model or game-ID alias cannot remove the exclusion.

The authoritative ledger is `server/artifacts/governance/mlb-final-oot-quarantine-v1.json`; enforcement is `final_oot_eligible_key_mask` plus `require_reduced_final_oot_report` in the quarantine module. Do not read retained raw quarantine scores as model evidence. The exception authorized source-history construction, not evaluation or selection.

Other standing boundaries:

- Preserve completed forecasts, simulations, failed attempts, withheld outputs and immutable receipts.
- Never publish after a declared deadline as if the result were pregame.
- Do not fit, tune or select from the current prospective duration outcomes.
- Do not change official V18, policy thresholds, positions, settlements or wagering authority through a research task.
- Preserve source restrictions, attribution and commercial-rights review requirements. Free access is not equivalent to subscriber-display or redistribution rights.
- Every newly trained candidate must retain the complete fitted estimator, fitted preprocessor, ordered feature contract and reload fixture. An OOF table alone is insufficient.
- Keep technical correctness, scientific validation, source licensing, product integration and decision authority as separate acceptance gates.

Source: [repository instructions](C:/Users/james/asp-model-studio/AGENTS.md), [quarantine ledger](C:/Users/james/asp-model-studio/server/artifacts/governance/mlb-final-oot-quarantine-v1.json).

## 13. Where construction should go next

This is an ordered recommendation for the incoming manager, not a new execution authorization.

### Immediate: finish the already authorized operational work

1. Preserve the running V18 publisher and let current-slate participant/source checks complete. Measure substantive per-game readiness and publication receipts, not heartbeat count.
2. Continue only still-open September 11 duration-pilot games in declared readiness/deadline order. Freeze each legitimate pair independently. Do not expand acquisition or manufacture a history for unsupported pitchers.
3. Score frozen pairs only after provenance-bearing finals; record actual BF gaps honestly; restore and verify NFL archiving under the existing completion/24-hour rule.
4. Have Claude verify the live AISP consumer configuration, the specific imported V18 objects and the conditional authority's actual ARMED/ACTIVE state. If the proposed model-era boundary has not been correctly implemented, do not claim it occurred.

### Next bounded integration phase

5. Close current-state geometry parity using the already accepted Play Geometry and Population Geometry builders/schemas. Preserve numerical forecast identities, perform exact reconciliation if deterministic replay is needed, and extend the current exchange/import route without changing models or page design.
6. Reconcile produced → packaged → imported → displayed counts with original availability timestamps. Separately account for source skips, pending checkpoints, access failures and missing consumer support. A package on disk is not a successful UI integration.
7. Restore the interactive Model Studio service when UI work is needed, using its intended local runtime. Do not restart or modify the independent publisher simply because the UI is not listening.

### Scientific work only after a separately bounded assignment

8. If PA hierarchy or another challenger study resumes, first repair/authenticate shared completion-ordered historical inputs and define a clean common Development cohort. Do not fit challengers against an unqualified historical baseline and call the comparison clean.
9. Accumulate prospective measurement before making model-performance claims. Keep operational acceptance, statistical inference and policy selection separate.
10. Leave NFL expansion, RF replacement/search, V19 reopening and broad NBA acquisition paused. Resume NBA only when the narrow entitlement/rights inquiry has a usable answer.

The highest-value direction is now a dependable daily chain—current evidence, correct frozen inputs, pregame forecasts, complete consumer artifacts, verified import and honest prospective measurement. A broader algorithm matrix is not the present bottleneck.

## 14. Repository state, evidence precedence and handoff instructions

Model Studio is on `codex/mlb-starter-duration-source-intake-v1` at **`9ca94e9c0135cde7d2b852560d59a43fa45a5c17`**. Recent commits include:

- `9f4e000`: frozen V18 conditional-champion registration and timing-qualified handoff;
- `2243a1c`: bounded starter-duration research and gated PA hierarchy;
- `951ebb2`: isolated paired pilot;
- `144e85a`: bounded source intake/readiness connection;
- `1b6fdbb`: completed authorized histories and permanent quarantine;
- `edc6f54`: first real prospective duration pair;
- `9ca94e9`: temporary monitoring/restoration protocol and final-gated scoring.

AISP was inspected on `claude/aisp-v18-and-price-coverage-v1` at **`a3574356ec7c883a27a831d9fd2340570bc95687`**, with no tracked modifications at inspection. Its untracked research/handoff files were preserved. Model Studio had existing tracked changes to September 10/11 current-slate locators and `outputs/nfl-play-level-engine-v1/CURRENT.json`; these were not reset, staged or rewritten for this report. This handoff itself is a new documentation artifact, not a code/deployment change.

Use the following evidence precedence:

1. Explicit current decisions from James and repository safety instructions.
2. Verified immutable artifacts/receipts at a stated time, plus current code and live metadata where actually checked.
3. Recent scoped implementation reports.
4. Older project summaries and README descriptions as historical context only.

`README.md` still contains early claims that no PA model/bundle exists. `docs/ARCHITECTURE.md` describes the inherited ATLAS foundation. The September 6 project-management handoff and AISP's September 8 handoff contain branch, port, import and activation descriptions that are now partly superseded. Do not initiate old remediation instructions solely because those historical documents exist.

### Suggested first message for the new project-management AI

> Use this September 11 handoff as an as-of technical map, not as permission to expand scope. James owns program decisions. Coordinate Model Studio implementation separately from Claude's AISP work. First preserve the active prospective pair measurement and verify its NFL restoration condition; then reconcile current V18 production, AISP import and conditional authority using actual receipts. Keep the permanent three-game quarantine and remaining OOT sealed. Do not reopen V19/RF/NFL/selection studies or infer betting authority from a forecast. Propose narrowly bounded work to close current-state geometry/exchange parity and remaining operational evidence gaps. Require exact estimator/preprocessor/feature-order/reload preservation for any future model training.

## 15. What this report did and did not verify

This report inspected relevant repository code/docs, Git metadata, current artifact metadata, exact scheduler metadata and listening ports. It verified eight saved forecast timestamp orderings and 32 bound file hashes/lengths. It read no game outcomes, sealed OOT payloads or raw quarantined source payloads; ran no models, simulations or test suites; made no sports-provider calls; changed no application, scheduler, policy, AISP database or production code.

It does not independently certify current AISP imported-row counts, live champion activation, automatic-import enablement, all three current simulator views, source freshness beyond the cited receipts, uptime after a future restart, commercial rights, calibrated prospective superiority or wagering profitability. Those are explicit follow-up facts, not implied by the substantial implementation already present.
