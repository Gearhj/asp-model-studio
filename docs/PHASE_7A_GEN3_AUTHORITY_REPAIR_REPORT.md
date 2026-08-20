# Phase 7A — Gen-3 Authority, Immutability, Blinding, Governed Baseline & Containment

**Branch:** `phase7-advanced-mlb-data-integration` · **Base HEAD:** `e9d3f64` · **No external data downloaded.**
Preserved untracked reports (`GPT56_SOL_INDEPENDENT_ASP_AUDIT.md`, `docs/PHASE_7_CORE_CODEX_ACCEPTANCE_REPORT.md`)
left unstaged and unmodified.

This phase repairs the foundations the Codex gate accepted-with-repairs: it makes Gen-3 governed,
content-addressed, immutable, physically 2025-blinded, quarantine-ledgered, and gives it a truthful
governed-baseline comparator — plus two inherited security fixes. The full platform **execution binding**
(server-authorized Model-Laboratory selection/execution of Gen-3 through the UI) is **not** completed and
is the remaining blocker; see the verdict.

---

## Codex findings addressed

| Codex "not accepted" item | Status this phase |
|---|---|
| Governed authority (contracts) | **Done** — 7 canonical digested contracts (Gate 1) |
| Immutable / content-addressed publication | **Done** — atomic `objects/sha256/<logical-sha>/`, tamper/link/conflict rejection (Gate 3/4) |
| Physical 2025 blinding | **Done** — separate research (2021-24) + sealed (2025) objects; default frame excludes 2025 (Gate 5) |
| Governed baseline equivalence | **Done** — governed FoldPreprocessor (mean+standardize) replay + reproduction gate (Gate 6) |
| Row-level quarantine ledger | **Done** — content-addressed, 139 records, reason-coded (Gate 2) |
| Innings 15/16 truthfulness | **Done** — Schema V2 includes them; 27 rows restored (Gate 2) |
| Registration (record) | **Partial** — immutable registration record written; not yet Data-Warehouse-integrated (Gate 7) |
| Data Warehouse visibility / selection | **Not done** — deferred (Gate 7/10) |
| Server-authorized execution / experiment identity | **Not done** — deferred (Gate 8/9/10) |
| Experiment-ID path traversal | **Done** — opaque-ID allowlist + resolved containment (Gate 11A) |
| User-Python host execution default | **Done** — disabled by default, opt-in only (Gate 11B) |

## Contracts (Gate 1) — `server/sports_modeling/gen3_contracts.py`

Seven canonical-JSON, SHA-256-digested, semantically-versioned contracts; each id is
`<NAME>:sha256:<digest>`. Contract-bundle SHA (Gen-3 authority fingerprint): **`f687706080e038000e618518b063ad46a92c5b1f604a2cf2cb27309eb28a250a`**.

| Contract | SHA-256 |
|---|---|
| MLB_GEN3_TARGET_CONTRACT_V1 | *(8-class taxonomy, frozen order)* |
| MLB_GEN3_FEATURE_SCHEMA_V2 | context_inning 1..16 (was ≤14) |
| MLB_GEN3_BASE_FEATURE_CONTRACT_V1 | 22 features, Gen-2-identical math |
| MLB_GEN3_KNOWLEDGE_TIME_CONTRACT_V1 | pregame-only; prior eligible_from ≤ S; 2021 prior-blind |
| MLB_GEN3_TEMPORAL_CONTRACT_V1 | `e35cff1c8aa21377…` — dev 2021-23, val 2024, sealed 2025, prospective 2026 |
| MLB_GEN3_PREPROCESSING_CONTRACT_V1 | `008426bbbf7abec1…` — fold-mean impute + standardize |
| MLB_GEN3_POPULATION_CONTRACT_V1 | `e2d61bd2859ca50d…` — accepted populations + quarantine rule |

Contracts are validated before publication and embedded (by id/digest) in every child object's Parquet
metadata + manifest.

## Schema V2 + row-level quarantine (Gate 2)

- **Innings 15–16 included.** The frozen Gen-2 schema capped `context_inning` at 14; the type is int16 and
  the feature semantics are unchanged, so the 27 real long-game PAs (2021: 20 in innings 15–16; 2022: 7 in
  inning 15) are now materialized. Quarantine drops from 166 → **139**.
- **Row-level quarantine ledger** (content-addressed, SHA `fec36f1bab43c627…`, **139 records**). Each record
  binds `plate_appearance_id`, `game_id`, `season`, `reasonCode = BATTING_TEAM_CONVENTION_ANOMALY`,
  `reasonDetail`, and `decisionRuleVersion = MLB_GEN3_POPULATION_CONTRACT_V1`. No outcome/metric-conditioned
  field. The two fully-quarantined games are `ANA202108101` (66) and `DET202205101` (73).
- **Label truthfulness:** the unproven "relocated / neutral-site home game" causal claim is removed; the
  defensible reason is the structural batting-team-vs-half convention conflict (fail-closed until source
  evidence resolves the exact score-difference semantics).

## Immutable publication (Gate 3/4) — `server/sports_modeling/gen3_publish.py`

Stage-on-destination → validate → fsync → hash → **atomic publish** under
`objects/sha256/<logical-content-sha>/`. Re-runs reuse an identical object and **reject tamper** (an
existing object whose logical content no longer hashes to its address, or is unreadable, is rejected).
Symlinks/reparse points in the publication path are rejected; resolved paths must stay within the objects
root. Critical identities (contract-bundle SHA, logical/schema SHA, temporal/feature/target contract ids,
code revision) are embedded in Parquet metadata **and** an external manifest carrying build-run id, source
partition ids, bridge manifest, dependency environment, dirty-tree state, and quarantine-ledger SHA.

## Physical 2025 blinding (Gate 5)

Two separate immutable objects:

| Object | Seasons | Rows | Logical content SHA |
|---|---|---|---|
| **research** | 2021–2024 | 730,284 | `05c91a1471385d30933356ce0026cf715bb4c7566ce035efe71c75af6ad39124` |
| **sealed-2025** | 2025 | 182,926 | `878a311bb56ee32b9e408651c6a69daee8feff3c60df1234e9148dd01bb0f555` |

The governed ablation opens **only** the research object and asserts `2025 ∉ seasons` before any fit
(verified live: `seasons present=[2021,2022,2023,2024] (2025 absent: True)`). There is **no CLI flag** to
score 2025 in the development harness; the sealed object exists for structural registration only. A future
secondary-OOT evaluation would be a separate authorized one-shot service (not implemented here).

## Governed baseline equivalence (Gate 6) — `scripts/phase7a_governed_ablation.py`

Uses the **exact governed pipeline**: `training.FoldPreprocessor` (fold-training-only **mean** imputation +
**standardization**), one-hot categorical context, multinomial lbfgs logistic (`penalty=l2`, `tol=1e-7`,
`max_iter=2000`), C selected over the frozen grid `(0.05, 0.2, 1.0)` via a chronological development-only
inner split (`chronological_date_atomic_split`, 0.8), **fail-closed on non-convergence**, with selected C
and `n_iter` persisted. HGB uses `early_stopping=False` (deterministic — no undeclared random inner split),
`n_iter_` persisted. A paired whole-game bootstrap on 2024 (2,000 seeded replicates, game-clustered)
quantifies uncertainty. Immutable prediction/metric/bootstrap evidence is bound to the research-object SHA,
contract-bundle SHA, and code revision. **2025 is never loaded, fit, tuned, selected, or scored.**

**Reproduction gate — PASSED.** Governed A0 (dev=2023) 2024 log loss = **1.48425485** vs target **1.484255**;
difference **1.5e-7** ≪ tolerance 1e-3. A0 is now a genuine governed Gen-2/D3/C4-policy replay (not the
Phase-7 median/no-scale comparator). Selected C=1.0, converged at nIter 1453/2000.

### Governed A0/A1/A2 (2024 validation; 2025 never loaded)

| Branch | Dev seasons | Dev rows | Model | Selected C | Val 2024 log loss | nIter | Top-1 | Macro-F1 |
|---|---|---:|---|---|---:|---:|---:|---:|
| A0 | 2023 | 184,104 | governed logistic | 1.0 | **1.48425485** | 1453 | 0.4516 | 0.0898 |
| A1 | 2022–2023 | 366,083 | governed logistic | 0.05 | **1.48259757** | 598 | 0.4525 | 0.0864 |
| A2 | 2021–2023 | 547,835 | governed logistic | 0.05 | **1.48273326** | 673 | 0.4524 | 0.0864 |
| A0 | 2023 | 184,104 | governed HGB (no early stop) | — | 1.50192959 | 200 | — | — |
| A1 | 2022–2023 | 366,083 | governed HGB | — | 1.49113214 | 200 | — | — |
| A2 | 2021–2023 | 547,835 | governed HGB | — | 1.49222912 | 200 | — | — |

Row counts increased slightly vs Phase 7 (A1 366,083, A2 547,835) because innings 15/16 are now included.
All logistic fits converged (fail-closed check armed); HGB used a fixed 200 iterations with early stopping
disabled (deterministic, no undeclared random inner split).

### Paired whole-game bootstrap on 2024 (2,000 game-clustered replicates; delta = left − right, negative = left better)

| Comparison | Observed delta | 95% CI | P(left better) | Interpretation |
|---|---:|---:|---:|---|
| A1 − A0 | −0.001657 | [−0.001932, −0.001395] | 1.00 | A1 robustly better than A0 |
| A2 − A0 | −0.001522 | [−0.001815, −0.001244] | 1.00 | A2 robustly better than A0 |
| A2 − A1 | +0.000136 | [+0.000060, +0.000213] | 0.00 | **A2 consistently worse than A1** |

Under the governed pipeline the training-volume conclusion is confirmed and slightly larger than the
Phase-7 median/no-scale estimate: adding 2022 (A1) is the best branch; adding the prior-blind 2021 (A2)
gives back part of the gain for the linear model. The absolute effect is still small (~0.0017 log loss) and
is conditional evidence on the already-used 2024 fold — **A1 is a research comparator, not a champion.**
This immutable evidence (predictions/metrics/bootstrap) is bound to research-object SHA `05c91a14…`,
contract-bundle SHA `f6877060…`, and the code revision.

## Security containment (Gate 11)

- **Path traversal (11A):** `modeling.get_experiment` now validates the id against an opaque allowlist
  (`^cockpit-(exp|autopilot)-[0-9a-f]{8,64}$`) and enforces resolved-path containment within the experiments
  root, rejecting symlinks — before any filesystem path is constructed. Verified: `../../secret`,
  `..%2f..%2fx`, `cockpit-exp-../x`, `/etc/passwd`, malformed ids all raise (router → HTTP 422); a
  valid-form absent id returns None.
- **User Python (11B):** `EXECUTION_ENABLED` default flipped to **disabled** (opt-in via
  `ATLAS_ENABLE_PYTHON_RUN∈{1,true,yes}`, never in hosted mode). Verified disabled with a clean environment;
  the existing python-execution test opts in explicitly and still passes.
- **Ownership scope:** the Gen-3 authority lives under the gitignored runtime root; full project/tenant
  scoping of registrations/experiments is part of the deferred platform-binding work.

## Tests (Gate 12) — `tests/sports_modeling_phase7a_authority_test.py`

Hermetic fail-closed gates: contract canonical determinism + digests; temporal contract seals 2025/2026;
preprocessing contract declares mean+standardize; publisher content-addressing + idempotent reuse + tamper
rejection + Parquet-metadata identity binding; symlink-object rejection (skips only if the OS forbids
symlink creation); experiment-id traversal rejection; user-Python disabled-by-default (subprocess, clean
env). Real-artifact acceptance (skip if unpublished): registration binds research+sealed; 2025 physically
absent from research; innings 15/16 present; quarantine = 139 convention-only; content-addressed row-level
ledger. Plus the existing `sports_modeling_phase7_gen3_test.py` (7) still valid.

## Remaining blockers (before Phase 7B acquisition is treated as authoritative / scientist-exposed)

1. **Server-side execution authority (Gate 8) + experiment identity (Gate 9):** a server-issued run
   authority binding dataset/version/content-SHA/target/temporal/preprocessing/feature/code, resolved and
   verified server-side, with experiment identity keyed on the full fingerprint (not the model-config hash).
2. **Data Warehouse registration + Data & Population selection + Model Lab execution binding (Gate 7/10):**
   Gen-3 as a selectable server-authorized dataset version that actually drives execution, with a
   Gen-2-vs-Gen-3 execution-distinction test.
3. **Project/tenant ownership scoping** of Gen-3 registrations and experiment artifacts.
4. (Data science) treat A1 as a research comparator only; advanced feature families are higher-leverage and
   require the deferred Statcast corpus.

## Verdict

**`PHASE_7A_BLOCKED`**

The data-authority, immutability, physical-blinding, governed-baseline, quarantine-ledger, and inherited-
security foundations are **complete and tested** — these are the gates that must exist before large
external acquisition is treated as authoritative ASP data (Codex Gates 1–4), and the governed A0
reproduction passed at 1.5e-7. However, the Phase-7A stop condition also requires **exact server-side
execution authority, full experiment identity in the live cockpit, and scientist-facing platform
selection/execution of Gen-3** (Gates 7–10). Those are deliberately **not** attempted here rather than
rushed, because they modify the D3/C4-serving cockpit execution path and the frontend, and a half-built
binding would risk the frozen champion. They remain open.

Therefore Gen-3 is now a **governed, immutable, registered (record-level), physically-blinded, baseline-
truthful research authority**, but it is **not yet server-authorized or scientist-selectable through the
application**. Advanced acquisition may proceed as bounded research, but its outputs must not be exposed
through ASP or treated as scientist-facing authority until Gates 7–10 are complete. Re-audit after the
platform-execution binding lands.
