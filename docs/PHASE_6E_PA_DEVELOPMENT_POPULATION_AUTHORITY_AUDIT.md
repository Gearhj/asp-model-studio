# Phase 6E — PA Development Population Authority Audit

Resolving the "2021–2023 contract vs. 2023-only modeling matrix" mismatch.

## 1. Executive Verdict

**`DEVELOPMENT_2023_ONLY_REQUIRED`.**

The registered dataset spans 2021–2025, but its **governing manifest deliberately classifies 2021–2022
as `PRIOR_ONLY_HISTORY`** — evidence retained *only* to construct Y−1 player priors for the primary
modeling seasons, and **contractually prohibited from primary target training**
(`PRIMARY_2023_2025_TARGET_TRAINING`). The PA modeling matrix (feature view, 549,479 rows) is therefore
2023–2025 by governance, with development = **2023**, validation = **2024**, frozen final = **2025**.

This is corroborated independently by the Y−1 prior data: the earliest registered `player_prior` source
season is **2021** (eligible from 2022). A 2021 *target* PA would require a ≤2020 prior, which does not
exist — so **every 2021 plate appearance would be prior-missing**, degrading a full third of any
"2021–2023" development set to a context-only feature regime. 2022 *could* draw 2021 priors, but 2022 is
itself a governance-prohibited `PRIOR_ONLY_HISTORY` target season.

The backend (feature contract, feature view, cockpit) was **already correct** (2023-only development).
The mismatch was entirely in the **frontend forecast contract**, which over-claimed development =
`[2021, 2022, 2023]`. This audit corrects the contract authority and displayed temporal policy so every
surface agrees with the governed window. **No feature view was rebuilt; D3/C4 is untouched; no model was
trained.**

## 2. Current Contract (as read)

| Field | Value |
|---|---|
| Project | MLB Plate Appearance Modeling – Gen 2 |
| Target | Plate-Appearance Outcome (8-class) |
| Lifecycle | Pregame — Final |
| Evidence mode | Strict Pregame / Enhanced (project choice) |
| **Development (claimed)** | **2021–2023** ← over-claim (frontend `DEFAULT_TEMPORAL`) |
| Validation | 2024 |
| Frozen final | 2025 |
| Prospective | 2026 |

Source of the over-claim: `src/sports/workflow/workflowState.ts` →
`DEFAULT_TEMPORAL.developmentSeasons = [2021, 2022, 2023]`, echoed by `ForecastContractPanel`,
`SportsProjectOverview`, and the cockpit intro fallback `"2021–2023"`.

## 3. Registered Dataset Coverage

Registered dataset `asp.mlb.open-data.fd1` (manifest SHA `1b58d5d1def2c9b7…`), read directly from
`sports-dataset-manifest.json`. `plate_appearance` family:

| Season | Registered PAs | Manifest season role |
|---|---:|---|
| 2021 | 181,818 | `PRIOR_ONLY_HISTORY` |
| 2022 | 182,052 | `PRIOR_ONLY_HISTORY` |
| 2023 | 184,104 | `PRIMARY_GEN2_MODELING` |
| 2024 | 182,449 | `PRIMARY_GEN2_MODELING` |
| 2025 | 182,926 | `PRIMARY_GEN2_MODELING` |
| **Total** | **913,349** | — |

`manifest.temporal_contract.season_roles` = `{"2021-2022": "PRIOR_ONLY_HISTORY", "2023-2025":
"PRIMARY_GEN2_MODELING"}`. The `prior_only` population (2021–2022, 1,491,533 rows across families)
carries prohibited-use `PRIMARY_2023_2025_TARGET_TRAINING` and `temporal_meaning`: *"History retained
for prior construction; never primary target rows."*

## 4. Current Feature-View Coverage

The materialized PA modeling matrix (`mlb-pa-feature-view-v1.parquet`, content SHA
`42884747dfb61056…`):

| Season | Rows | Role |
|---|---:|---|
| 2023 | 184,104 | development |
| 2024 | 182,449 | validation |
| 2025 | 182,926 | frozen_final |
| **Total** | **549,479** | — |

Contract `MLB_PA_FEATURE_VIEW_V1`, schema unchanged, 22 features (5 context + 8 batter + 9 pitcher),
8-class target `outcome`. `feature_contract.TARGET_SEASONS = (2023, 2024, 2025)`.

## 5. Where 2021/2022 Disappear

Three concentric authorities, all pointing the same way — **not a single leaky filter**:

1. **Governance (root cause):** `manifest.temporal_contract` classifies 2021–2022 as
   `PRIOR_ONLY_HISTORY`; the `prior_only` population prohibits `PRIMARY_2023_2025_TARGET_TRAINING`.
2. **Feature contract:** `server/sports_modeling/feature_contract.py` → `TARGET_SEASONS = (2023, 2024,
   2025)`, `EXPECTED_SEASON_ROWS` and `EXPECTED_TOTAL_ROWS = 549_479` freeze the modeling seasons.
3. **Feature view builder:** `server/sports_modeling/feature_view.py` selects only PA partitions with
   `season in TARGET_SEASONS`, and enforces per-row `population_category == "GEN2_PRIMARY_2023_2025"`
   and `strict_population == "GEN2_STRICT_DEPLOYABLE_RECONSTRUCTION"`. Prior partitions are read for
   `season <= max(TARGET_SEASONS) - 1` (i.e. 2021–2024) — 2021–2022 flow in **as priors**, never as
   targets.

The cockpit (`engine.py`, `DEV_SEASON=2023`) simply consumes this matrix. The only surface that ever
said "2021–2023 development" was the client contract default.

## 6. Root Cause

**Classification: B — GOVERNANCE REQUIRED** (with independent scientific corroboration under Part C).

The dataset publisher scoped 2021–2022 to prior construction by contract. The frontend
`DEFAULT_TEMPORAL` conflated *source-evidence span* (2021–2025) with *modeling-development window*
(2023). It was an **optimistic UI over-claim**, not a data pipeline that silently dropped valid rows.

## 7. Y−1 Batter Prior Feasibility

`player_prior` registered source seasons and eligibility (read from parquet):

| Source season | Rows (BATTING) | eligible_from |
|---|---:|---|
| 2021 | 1,508 | 2022 |
| 2022 | 1,495 | 2023 |
| 2023 | 1,457 | 2024 |
| 2024 | 1,454 | 2025 |
| 2025 | 1,470 | 2026 |

- **2021 target** needs source ≤ 2020, eligible_from ≤ 2021 → **none exist** → 100% batter-prior-missing.
  **Infeasible.**
- **2022 target** needs source ≤ 2021, eligible_from ≤ 2022 → 2021 priors qualify → **feasible** at
  normal missingness (debut players only). *But 2022 is governance-prohibited as a target season.*

## 8. Y−1 Pitcher Prior Feasibility

Identical structure (PITCHING domain: 909/871/863/855/873 rows for 2021–2025, eligible_from = season+1).

- **2021 target**: no ≤2020 pitcher prior → 100% pitcher-prior-missing → **infeasible**.
- **2022 target**: 2021 pitcher priors available → feasible, modulo governance prohibition.

## 9. Missing-History Policy (existing behavior)

The feature contract already has a **debut/cold-start fallback**: `batter_prior_missing` /
`pitcher_prior_missing` boolean indicators plus **fold-training-only mean imputation**. Confirmed
missingness on the current matrix (`EXPECTED_PRIOR_COVERAGE`):

| Season | Batter missing | Pitcher missing |
|---|---:|---:|
| 2023 | 15,099 (8.2%) | 24,536 (13.3%) |
| 2024 | 11,855 (6.5%) | 21,535 (11.8%) |
| 2025 | 15,206 (8.3%) | 18,248 (9.9%) |

This fallback is designed for a **minority** of genuinely-debuting players against a backdrop where
most players carry priors. It does **not** legitimize 2021, where the missing rate would be **100%**:
the prior columns collapse to constants, the `*_prior_missing` indicators become perfectly collinear
with a "season == 2021" flag, and 2021 degenerates to a context-only regime. Applying the debut
fallback to a whole season is a **new** application of the policy, not existing modeled behavior — and
Phase 6E is explicitly forbidden from inventing fallback policy. 2021 stays out.

## 10. Feature-by-Feature Availability

| Feature family (count) | 2021 | 2022 |
|---|---|---|
| Context: inning, top/bottom, outs, base-mask, score-diff (5) | AVAILABLE | AVAILABLE |
| Batter Y−1 rate/volume (7) | **UNAVAILABLE** (no ≤2020 prior) | AVAILABLE |
| `batter_prior_missing` (1) | AVAILABLE but constant-True | AVAILABLE |
| Pitcher Y−1 rate/volume (8) | **UNAVAILABLE** (no ≤2020 prior) | AVAILABLE |
| `pitcher_prior_missing` (1) | AVAILABLE but constant-True | AVAILABLE |

2021: 14 of 22 features carry zero signal. 2022: all features available — but blocked by governance.

## 11. Strict-Pregame Audit

No extension is performed, so no new leakage surface is introduced. For the record, both candidate
seasons obey the Strict-Pregame timing contract: `player_prior` rows use `eligible_from_season =
season + 1` (Y−1-or-earlier only; `same_season_predictor_eligible = False`), and PA context features
are pre-terminal in-PA state. No target-game lineup, postgame, or future-season information is used.

## 12. Candidate Development Windows

| Candidate | Rows (dev) | Feature completeness | Existing fallback | Leakage | Governance | Verdict |
|---|---:|---|---|---|---|---|
| A — 2021–2023 | 547,974 | 2021 context-only | would need whole-season fallback (new policy) | none new | **prohibited** (2021+2022 = PRIOR_ONLY_HISTORY) | **INVALID** |
| B — 2022–2023 | 366,156 | 2022 complete | normal | none new | **prohibited** (2022 = PRIOR_ONLY_HISTORY) | **INVALID** |
| C — 2023 only | 184,104 | complete | normal (debut only) | none | `PRIMARY_GEN2_MODELING` | **VALID** |

## 13. Selected Development Window

**2023 only** (Candidate C). Decision order (Part F): 2021 invalid → 2022 invalid (governance) → retain
2023. Not chosen on model performance; chosen on data validity, feature availability, temporal
integrity, and governance.

## 14. Row Reconciliation

| Season | Registered | Eligible as modeling target | Excluded | Reason |
|---|---:|---:|---:|---|
| 2021 | 181,818 | 0 | 181,818 | PRIOR_ONLY_HISTORY + no ≤2020 prior |
| 2022 | 182,052 | 0 | 182,052 | PRIOR_ONLY_HISTORY (prohibited target) |
| 2023 | 184,104 | 184,104 | 0 | development |
| 2024 | 182,449 | 182,449 | 0 | validation |
| 2025 | 182,926 | 182,926 | 0 | frozen final |

Modeling matrix total = 549,479 (unchanged). 2021–2022 remain fully available as **source evidence /
prior construction** in the Data Warehouse.

## 15. Missingness by Season

Modeling matrix only (2023–2025); see §9. Adding 2021 would have raised prior-missingness to 100% for
that season — the decisive quantitative reason it is excluded. No global imputation was introduced; the
fold-training-only policy is unchanged.

## 16. Identity / Leakage by Season

Identity resolution is exact-canonical-UUID for all registered seasons (bridge dimension field
`prior_history_2021_2022` confirms 2021–2022 participate only as prior history). The modeling matrix
contains **only** 2023–2025 rows (regression-tested), so no 2021/2022 identity ambiguity can leak into
development. Unresolved/ambiguous references on the matrix remain 0.

## 17. Artifact Authority

**No new artifact materialized** (2023-only retained). Existing authority, unchanged:

- Parent dataset manifest SHA: `1b58d5d1def2c9b79041472974e93bc9a0f4c5317210099c1b1ee531fbfe8b49`
- Feature contract: `MLB_PA_FEATURE_VIEW_V1`, `TARGET_SEASONS = (2023, 2024, 2025)`
- Feature view content SHA: `42884747dfb610564bf0c85ab30f6c16d09b2a01982ddbc4e9ccb485f2ddb53f`
- Rows: 549,479 · Columns: 22 features + lineage · gitignored runtime artifact (unchanged)

No rematerialization, no pickle/joblib serialization introduced; idempotency preserved (nothing rebuilt).

## 18. Cockpit Reconciliation

All surfaces now report the same window:

| Surface | Development | Validation | Frozen |
|---|---|---|---|
| Forecast contract (`GOVERNED_TEMPORAL`) | 2023 | 2024 | 2025 |
| Stage 2 Data Evidence & Quality | 2023 (+ source-evidence 2021–2025 note) | 2024 | 2025 |
| Stage 3 PA Model Development intro | 2023 | 2024 | 2025 |
| Cockpit 02 Data & Population (`population_payload`) | [2023] | 2024 | 2025 |
| Cockpit 08 Temporal Split | 2023 | 2024 | 2025 |
| Project Overview temporal policy | 2023 → 2024 → 2025 | — | — |

Legacy saved contracts that stored `[2021,2022,2023]` are reconciled at display time via
`governedDevelopmentSeasons()` — shown as 2023, never silently claimed as 2021–2023.

## 19. Historical Champion Treatment

**HISTORICAL CHAMPION: D3 / C4** — trained under the prior frozen protocol
(FIT_2023 → VALIDATE_2024 → REFIT_2023-2024 → VALIDATE_2025). Not retrained, not overwritten by this
audit. **GEN-2 CHALLENGERS** will use the same governed development authority (2023). The population
authority did not change — it was already 2023; only the *displayed contract* was corrected.

## 20. Tests

- `tests/sportsPopulationAuthority.test.mjs` (frontend, 9): governed window = [2023]; default no longer
  claims 2021–2023; legacy contract reconciled to 2023; 2025 never development; 2024 validation;
  2021–2022 = source-only prior history; contract panel restricts dev selection; overview/intro use the
  governed helper.
- `tests/sports_population_authority_test.py` (backend, 8): feature contract seasons = (2023,2024,2025);
  22 features / 8-class target unchanged; engine constants agree; `population_payload` development=[2023]
  / val=2024 / frozen=2025 + `sourceEvidence` block; matrix contains no 2021/2022 rows; objective &
  preview agree.

## 21. Known Limitations

- Contract/adoptions remain client-side localStorage (documented Phase 6C limitation); the governed
  reconciliation clamps display but cannot rewrite a user's stored JSON — it renders it honestly.
- 2021–2022 remain valuable **only** as Y−1 prior source evidence; they can never become modeling
  targets without new ≤2020 prior evidence *and* a governance change to the dataset manifest.
- No premium contact-quality / handedness data added (out of scope).

## 22. Exact Next Scientist Action

Open **MLB Plate Appearance Modeling – Gen 2 → Stage 3 — PA Model Development → 03 Data Profile** and
examine Information Value, Mutual Information, target relationships, feature distributions, missingness,
outliers, temporal stability, correlation/redundancy, and possible leakage across the governed
**2023** development population before constructing the first Gen-2 challenger. The owner and ChatGPT own
that modeling decision; this task does not make it.
