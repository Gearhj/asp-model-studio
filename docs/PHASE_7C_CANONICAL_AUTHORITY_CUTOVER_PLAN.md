# Phase 7C — Canonical Scientific Authority Cutover — PLAN (Gate 0)

**Branch:** `phase7c-canonical-authority-cutover` · **Starting HEAD:** `7eb8de556682108d86b6ea1135a3085fe16703da`
**Worktree at entry:** clean; untracked = preserved audit/Codex reports only.

This plan is the Gate-0 cutover map. It is derived from the independent Codex acceptance report
(`docs/PHASE_7A5_CODEX_FINAL_ACCEPTANCE_REPORT.md`) plus a full code inventory of the legacy scientist
paths (backend) and the competing frontend authorities. Implementation follows this map.

---

## Preflight facts

- **Gen-3 provenance mismatch (P0-03) confirmed.** `.runtime/.../mlb-pa-gen3-v2/registration.json` records
  contract bundle `f687706080…` and knowledge-time **V1** `0a690986…`. Current code
  (`server/sports_modeling/gen3_contracts.py`) computes bundle `86a60f6caefc…` and knowledge-time **V2**
  `6ab2d6e5…`. The live object is content-addressed under V1; `create_binding` stamps V2. → **republish V2**.
- **Gen-2 has no physical separation.** `engine.load_frame()` loads a single combined parquet
  `mlb-pa-feature-view-v1.parquet` (seasons 2023/2024/2025) via a hardcoded glob (`engine.py:57-65,165-204`),
  caches it, and every legacy route slices it in memory. `gen3_authority.catalog()` calls
  `_gen2_catalog_entry()` which **opens/hashes that combined object on every catalog read**
  (`gen3_authority.py:125-137,165-166`).
- **`_verify_object` is incomplete** (`gen3_authority.py:190-210`): checks physical SHA, rows, seasons;
  computes a schema digest as `[{name,type}]` (omits `nullable` that the publisher includes at
  `gen3_publish.py:84-86`). Does not verify logical content SHA, embedded metadata, bundle, contract IDs,
  object kind, or generation. Forged logical/generation/schema/bundle were accepted in the audit.
- **Evidence is thin** (`gen3_authority.py:500-540`): no fitted estimator, no validation predictions, no
  confusion/reliability diagnostics → downstream cannot recompute metrics.
- **Frontend `lastResult` has no live writer** (`setLastResult` uncalled); the only writer path is disabled
  (`cockpitSteps2.tsx:63-65`). Yet Evaluation/Calibration/Champion/Registry (Steps 11/12/14/15) gate real
  content on it. `lastSim` is written only by `SimulationStep` after binding-free `/cockpit/simulate`.
- **Field bug**: UI reads `result.sealedSeasonsLoaded` (`Gen3AuthorityPanel.tsx:23,144`); backend returns
  `sealedSeasonsAccessed` (`gen3_authority.py:535`) → successful-run render crash.

---

## Cutover map

| Legacy capability | Current authority | Target canonical authority | Migration | Retirement | Acceptance test |
|---|---|---|---|---|---|
| Gen-2 modeling dataset | combined 2023–2025 object opened by `catalog()`/`load_frame()` | `MLB_GEN2_RESEARCH_2023_2024` immutable object (no 2025) + registry receipt | publish separate research/sealed Gen-2 objects; catalog resolves from registry | combined object → archived lineage; removed from ordinary resolver | hermetic: catalog/population open research only, 0 combined-object opens |
| Gen-3 research object (V1 bundle) | `registration.json` V1; binding stamps V2 | `MLB_GEN3_RESEARCH_V2` content-addressed under bundle `86a60f6c…` | re-run publisher under current V2 contracts; archive V1 registration as lineage | never bind V2 authority to V1 content | receipt verifies bundle/KT-V2 == binding |
| 2025 (both gens) | combined objects; sealed 2025 object exists but ordinary paths still read combined 2025 | separate `*_SEALED_2025_*` objects, non-selectable, `READ_SEALED_TARGET_DATA` not granted to ordinary routes | physical split (done for Gen-3, add for Gen-2) | ordinary resolver cannot open sealed | hermetic: sealed opens=0, target reads=0 |
| `/cockpit/experiment/run` | binding-free in-process fit, scores 2025 (`modeling.py:528`) | `/cockpit/gen3/execute` (authorized) | already migrated | **410 GONE** | caller inventory; 410 test |
| `/cockpit/feature/ablation` | binding-free, computes `delta2025`, uses it in verdict (`modeling.py:721-741`) | canonical 2024-only run evidence OR disabled | disable (NOT CONFIGURED) this phase | **410 GONE** | ablation route 410; UI shows NOT CONFIGURED |
| `/cockpit/simulate` + `/cockpit/eligibility` | binding-free, accepts 2025 (`simulation.py:236,394`) | active-run-bound 2024-only OR disabled | disable (NOT CONFIGURED) this phase | **410 GONE** | simulate route 410; UI shows NOT CONFIGURED |
| `/cockpit/autopilot` | binding-free, scores 2025 (`modeling.py:824`) | `/cockpit/gen3/run-suite` (authorized) | already migrated | **410 GONE** | 410 test |
| `/cockpit/target-analysis` | binding-free, returns 2025 per-season distribution (`engine.py:664-700`) | research-only target metadata from registered target contract | derive from research object 2023/2024 (Gen-2) or 2021-2024 (Gen-3) | 2025 removed; combined-object retired | no 2025 season in payload |
| `/cockpit/data-preview` | binding-free, season-selectable incl. 2025 (`engine.py:581-661`) | research-only preview from active binding research object | reject season 2025; research object only | combined-object retired | preview cannot return 2025 |
| `/cockpit/population`, `/cockpit/objective`, profile/correlation/outliers/missing/segmentation/temporal-split | binding-free over combined frame | active-binding-derived where material; descriptive-only otherwise | Data & Population from binding; others read research object | 2025 exposure removed | hermetic 0 sealed/combined opens |
| Frontend `lastResult`/`lastSim` authority | Zustand browser state, no live writer | server active candidate evidence bundle | Evaluation/Calibration/Registry read active candidate; Simulation blocks | remove `lastResult` gating | behavioral: run→activate→Evaluation populated |
| Frontend `notes["dataset.selected"]`/`["target.confirmed"]` | `store.notes`+localStorage (`readAuthorityState` cockpitSteps1:42-58) | active binding + registered target contract | ObjectiveStep/DatasetSection/TargetSelector derive from binding | remove note/localStorage selection+confirmation authority | behavioral: target derives from binding |
| `sealedSeasonsLoaded` UI field | mismatched name → crash | canonical `sealedSeasonsAccessed` shared schema | rename in UI | — | render test |

---

## Execution order (per the phase's own discipline)

1. **Data foundation** — Gate 2 (republish Gen-3 V2), Gate 1 (publish Gen-2 research/sealed + migration audit), Gate 3 (generation-correct registrations).
2. **Registry + verification** — Gate 4 (one immutable registry resolver, no combined-object open on catalog), Gate 5 (shared publisher/consumer digest), Gate 6 (complete receipt verification), Gate 7 (physical sealed-data policy / research-only resolver).
3. **Execution + evidence** — Gate 16 (complete run-evidence bundle: estimator, preprocessor, predictions, diagnostics), Gate 17 (active candidate sole downstream parent), Gate 14/15 (attempt lifecycle, post-fit drift), Gate 12/13 (strict schemas, bounded scheduler).
4. **Route retirement** — Gate 11 + Gate 26 (410 GONE for binding-free execution + 2025-exposing endpoints), Gate 21 (ablation), Gate 20 (simulation), Gate 22 (target/preview), Gate 23 (Data & Population).
5. **Frontend consolidation** — Gate 8/9/10 (one authority provider, remove note/lastResult authority), Gate 18/19 (Evaluation/Calibration active-run), Gate 24 (field consistency), Gate 25 (project switch).
6. **Verification** — Gate 27 (hermetic production-resolver), Gate 28 (two-user/two-project E2E), Gate 29 (A2 current-HEAD reproduction), Gate 30 (D3/C4 protection), Gate 31 (behavioral frontend), Gate 32 (security regression).
7. **Close** — Gate 33 (report), Gate 34 (coherent commits), post-commit re-acceptance.

Capabilities that cannot be safely and fully migrated within the phase budget will be marked
**NOT CONFIGURED** (endpoint returns 410 / UI states it explicitly) rather than left as an unsafe path,
per the phase authorization. The final report will record every such decision honestly.
