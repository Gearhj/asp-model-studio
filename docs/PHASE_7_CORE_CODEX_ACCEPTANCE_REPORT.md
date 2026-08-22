# Phase 7 CORE — Independent Codex Acceptance Gate

**Audit date:** 2026-08-20

**Repository:** `C:\Users\james\asp-model-studio`

**Branch:** `phase7-advanced-mlb-data-integration`

**Audited HEAD:** `e9d3f64b53c6c0393da06a543169eb7aa858e54f`

**Comparison base:** `a95b197841f534a97c16fbfc3e9026d713f4725f`

**Role:** independent adversarial reviewer

## Verdict

`PHASE_7_CORE_ACCEPTED_WITH_REPAIRS_REQUIRED`

The local Gen-3 materialization is real, its row reconciliation closes, its natural keys are unique, its 2023–2025 overlap is strictly identical to Gen-2 across all 33 columns, and the stored A0/A1/A2 validation metrics were independently reproduced without loading the sealed scoring season. This is sufficient to accept the Phase 7 work as **bounded local research evidence**.

It is not sufficient to call Gen-3 governed, immutable, registered, selectable, or server-authorized. The artifact is a mutable fixed-path Parquet plus mutable JSON sidecars; the named temporal contract is documentation rather than registered executable authority; the ablation is not a replay of the governed Gen-2 preprocessing contract; the default harness loads the nominally sealed season; and no product execution path can select Gen-3. These are release blockers before large-scale acquisition is treated as authoritative ASP data or before Gen-3 is exposed through the application.

No 2025 model score was computed or disclosed by this audit. Checks involving 2025 were limited to structural row counts, keys, schema, and exact parity against the already-governed Gen-2 overlap.

## 1. Repository and artifact inventory

### Repository state

| Item | Independent result |
|---|---|
| Branch | `phase7-advanced-mlb-data-integration` |
| HEAD | `e9d3f64b53c6c0393da06a543169eb7aa858e54f` |
| Base | `a95b197841f534a97c16fbfc3e9026d713f4725f` |
| Phase 7 commits | `f45e8d6` (builder, feature view, plan/report); `e9d3f64` (ablation, tests, report) |
| Tracked delta | Seven added files, 928 insertions; no pre-existing application, registry, router, or loader file changed |
| Diff hygiene | `git diff --check a95b197..HEAD` passed |
| Initial worktree | Only pre-existing `?? GPT56_SOL_INDEPENDENT_ASP_AUDIT.md`; preserved and never staged or edited |
| Focused test | `7 passed` with bytecode and pytest cache disabled |

The seven Phase 7 files are:

1. `docs/PHASE_7_ADVANCED_MLB_CORPUS_IMPLEMENTATION_REPORT.md`
2. `docs/PHASE_7_ADVANCED_MLB_DATA_INTEGRATION_PLAN.md`
3. `docs/PHASE_7_DATA_VALUE_ABLATION_REPORT.md`
4. `scripts/phase7_ablation.py`
5. `scripts/phase7_build_gen3.py`
6. `server/sports_modeling/feature_view_gen3.py`
7. `tests/sports_modeling_phase7_gen3_test.py`

This narrow delta is positive containment evidence: Phase 7 did not alter D3/C4 training, the frozen Gen-2 view, the cockpit API, the registry, or UI execution code.

### Parent authorities

| Authority | Verified identity |
|---|---|
| Dataset | `asp.mlb.open-data.fd1` |
| Dataset version | `asp.mlb.open-data.fd1:sha256:1b58d5d1def2c9b79041472974e93bc9a0f4c5317210099c1b1ee531fbfe8b49` |
| Dataset manifest | `sports-dataset-manifest:sha256:1b58d5d1def2c9b79041472974e93bc9a0f4c5317210099c1b1ee531fbfe8b49` |
| Dataset registration | `sports-dataset-1b58d5d1def2c9b7` |
| Partition authority SHA-256 | `8dec143b06622af068665b9fd1ad419a0353e76f0e0083b4c3459b8fce3cb437` |
| Identity bridge manifest | `sports-identity-bridge-manifest:sha256:6b69e7dcf4c5db7615420ee9f6f6f797b0335e31ab475646291f3a4cf90c52cf` |

The builder validates the registered package and bridge before reading selected partitions (`scripts/phase7_build_gen3.py:58-89`). The input consumers provide meaningful path, hash, schema, and row-count checks. The weakness is in the identity and publication of the **derived output**, not evidence that the present source was arbitrary.

### Gen-2 authority

| Item | Verified value |
|---|---|
| Registered feature-view ID | `mlb-pa-feature-view:sha256:74b9c24bb57dd75061a5de0f967c4a57e492eab9e016be950a036292bf8f958b` |
| Logical content SHA | `74b9c24bb57dd75061a5de0f967c4a57e492eab9e016be950a036292bf8f958b` |
| Physical Parquet SHA-256 | `42884747dfb610564bf0c85ab30f6c16d09b2a01982ddbc4e9ccb485f2ddb53f` |
| Rows | 549,479 |
| Seasons | 2023–2025 |
| Feature contract | `MLB_PA_FEATURE_VIEW_V1` |
| Feature-contract SHA-256 | `fc3227fe1488f0cf422dc40c634a9b0b1c432828d479a68ea6ba7a0dce038d1e` |
| Schema | `MLB_PA_FEATURE_SCHEMA_V1` |
| Schema SHA-256 | `1660eed54bf3904c2f2306d5a0171e7df6bf87fdc4fa9d39fb5ec2e8e741afd6` |

Gen-2 computes logical content, contract, and schema hashes, embeds those plus code revision in Parquet metadata, and publishes via a content-addressed/atomic runner (`server/sports_modeling/feature_view.py:316-365,595-621`; `server/sports_modeling/runner.py:150-215`). That is the appropriate minimum pattern for Gen-3.

### Gen-3 runtime artifacts

Runtime root:

`C:\Users\james\asp-model-studio\.runtime\asp-model-studio\sports-modeling\mlb-pa-gen3-v1`

| Artifact | Verified result |
|---|---|
| `mlb-pa-gen3-feature-view-v1.parquet` | 15,517,796 bytes; 913,183 rows; 33 columns; one row group |
| Physical Parquet SHA-256 | `a11d287372f30552424895751f7ae280182257cfb554e9bfd8a4426da82dd381` |
| `gen3-reconciliation.json` SHA-256 | `50e6165495ffa8f28afaf49677ec20094f83ad54d115c25f3dc859ec5fdb00d5` |
| `phase7-ablation.json` SHA-256 | `60e6ec71c75f7f0df0792ccd89cd9cb035ee01cc35a698b4aba824125e56e6b9` |

The recorded Parquet SHA currently matches the bytes. That does **not** make it content-addressed: its path is fixed, it is directly overwritten, and the SHA is computed only after the overwrite (`scripts/phase7_build_gen3.py:34-37,94-99`). The Parquet has ordinary Arrow schema metadata but no ASP content, feature-contract, temporal-contract, parent-manifest, or code-revision binding.

Gen-3 has no registered feature-view ID, logical content SHA, feature-contract ID/SHA, schema ID/SHA, registration ID, or logical URI. `MLB_GEN3_TEMPORAL_CONTRACT_V1` exists as a documentation label (`docs/PHASE_7_ADVANCED_MLB_DATA_INTEGRATION_PLAN.md:95-100`); code contains bare season constants (`server/sports_modeling/feature_view_gen3.py:38-43`) but no canonical payload or digest.

## 2. Claim-by-claim acceptance matrix

| Handoff claim | Result | Independent conclusion |
|---|---|---|
| Parallel Gen-3 PA view built | **Verified** | The local Parquet exists and has 913,183 rows/33 columns. |
| 2021–2023 are executable development targets | **Verified locally** | Actual A2 matrix contains all three seasons and 547,808 rows. This is not registered product authority. |
| 2024 is the only selection/validation season | **Verified for the direct harness** | All six fits use the same 182,449 2024 validation rows; HGB also uses an undeclared internal random development subset for early stopping. |
| 2025 is sealed and never automatically scored | **Partially verified / wording rejected** | Default execution does not score it, but loads it into the process and compares its rows during parity. An explicit flag scores it. It is not physically blinded. |
| 2021–2023 development has 547,808 rows | **Verified** | 181,732 + 181,972 + 184,104 = 547,808. |
| Complete Gen-3 has 913,183 rows | **Verified** | Parquet metadata and independent count agree. |
| 166 source observations quarantined | **Verified** | Exact source-key difference is 166 with no extras or unexplained losses. |
| Quarantine is 139 convention + 27 inning >14 | **Verified mechanically** | Predicates and source rows reproduce exactly; scientific strength differs by reason. |
| 2023–2025 base values match Gen-2 with zero mismatches | **Verified more strongly than harness** | Strict 33-column equality on all 549,479 aligned rows, including identity, target, lineage, feature values, missingness, and types. |
| A0/A1/A2 volume experiments are comparable | **Conditionally true, overstated** | Same direct-script preprocessing/families/validation; not a governed Gen-2 A0 replay, A2 has a qualitatively different missing-history mixture, and HGB has hidden internal random early stopping. |
| D3/C4 and Gen-2 not modified | **Verified** | No tracked Phase 7 delta reaches them; existing artifact hashes/mtimes predate Phase 7 and still match their identities. |

## 3. Row reconciliation and quarantine

### Exact closure

| Season | Source PA rows | Eligible before anomaly quarantine | Convention quarantine | Inning >14 quarantine | Final Gen-3 rows |
|---:|---:|---:|---:|---:|---:|
| 2021 | 181,818 | 181,818 | 66 | 20 | 181,732 |
| 2022 | 182,052 | 182,052 | 73 | 7 | 181,972 |
| 2023 | 184,104 | 184,104 | 0 | 0 | 184,104 |
| 2024 | 182,449 | 182,449 | 0 | 0 | 182,449 |
| 2025 | 182,926 | 182,926 | 0 | 0 | 182,926 |
| **Total** | **913,349** | **913,349** | **139** | **27** | **913,183** |

All 913,349 source rows pass the declared population and timing gates. The final count closes exactly:

`913,349 − 139 − 27 = 913,183`.

The source-to-output key set has 166 missing keys, zero extra keys, and the 166 missing keys match the builder predicates exactly. No outcome-conditioned or metric-conditioned exclusion was found.

### Convention quarantine: deterministic and defensible, label not proven

The 139 rows are two complete game populations:

- 2021 `retrosheet:game:ANA202108101`: 66 rows
- 2022 `retrosheet:game:DET202205101`: 73 rows

For every affected row, the stored batting-team ID conflicts with the builder's home/visitor-by-half convention used to calculate score difference. The predicate is structural and outcome-independent (`server/sports_modeling/feature_view_gen3.py:131-140`). Failing closed rather than emitting a possibly signed-wrong score feature is scientifically defensible.

The documentation's causal description as “relocated / neutral-site home games,” including its example, is not established by an explicit source flag in the persisted evidence. The exact defensible statement is “batting-team convention anomaly.” A row-level immutable quarantine ledger is also missing; the JSON retains counts only.

### Inning >14 quarantine: deterministic but weakly justified

The 27 rows comprise 20 plate appearances in 2021 innings 15–16 and seven in 2022 inning 15. The filter is deterministic and outcome-independent (`server/sports_modeling/feature_view_gen3.py:112-122`). It preserves the old `context_inning <= 14` schema boundary, but the underlying type can represent 15/16 and the feature's semantics do not change. This is compatibility precedent, not a compelling scientific exclusion.

Recommended repair: version the Gen-3 schema to admit legitimate innings 15/16, or document a domain reason and quantify sensitivity. Until then the current artifact slightly conditions the target population against unusually long games.

## 4. Natural keys, identity, and fan-out

| Check | Source | Gen-3 | Result |
|---|---:|---:|---|
| PA rows | 913,349 | 913,183 | Difference is exactly documented quarantine |
| Unique PA IDs | 913,349 | 913,183 | No duplicate target PA |
| Games | 12,148 | 12,146 | Two fully quarantined convention games account for difference |
| Extra output PA keys | — | 0 | No fan-out or fabrication |
| Unexplained missing PA keys | — | 0 | No silent loss beyond quarantine |

Per-season games are source→output: 2021 2,429→2,428; 2022 2,430→2,429; 2023 2,430→2,430; 2024 2,429→2,429; 2025 2,430→2,430. The two inning-tail filters remove only late PAs from one additional game in each of 2021 and 2022; they do not duplicate or split games.

All `(season, game_id, plate_appearance_id)` tuples are unique. Batter and pitcher bridge coverage is exact: 913,349 references for each role, with zero unresolved, ambiguous, or multiply mapped references in the source population. Prior lookup is a dictionary keyed by `(target season, canonical player, domain)` after duplicate prior keys are rejected (`server/sports_modeling/feature_view.py:262-313`), so it cannot multiply PA rows.

## 5. Actual temporal execution proof

The Phase 7 harness does not consume the named constants as an executable temporal-contract object. It independently hard-codes branch season lists and validation selection (`scripts/phase7_ablation.py:136-145`). Nevertheless, the actual matrices match the intended branch definitions:

| Branch | Development seasons | Fit rows | Expanded columns | Validation season | Validation rows |
|---|---|---:|---:|---|---:|
| A0 | 2023 | 184,104 | 32 | 2024 | 182,449 |
| A1 | 2022–2023 | 366,076 | 32 | 2024 | 182,449 |
| A2 | 2021–2023 | 547,808 | 32 | 2024 | 182,449 |

Independent recomputation began with a filtered Parquet read and asserted that the in-memory season set was exactly `{2021, 2022, 2023, 2024}` (730,257 rows). Therefore the independent fit/metric/uncertainty work provides direct evidence that:

- 2021 enters the A2 fit;
- 2022 enters A1 and A2 fits;
- 2023 enters all fits;
- 2024 enters no fit and is the common external validation set;
- 2025 enters no audit fit, tuning, selection, bootstrap, or scoring operation.

For the shipped harness, the statement needs qualification. It calls `pd.read_parquet(GEN3)` before masking (`scripts/phase7_ablation.py:113-124`), so all seasons in the file are resident and the nominally sealed season participates in the default parity comparison. Default execution does **not** score it. Scoring exists behind `--run-secondary-oot-2025` (`scripts/phase7_ablation.py:109-112,153-160`). Thus “not auto-scored” is correct; “sealed” or “not loaded into the comparison path” is not.

## 6. 2021 prior-blind semantics

Direct inspection of all 181,732 materialized 2021 rows found:

- batter prior season is null on every row;
- pitcher prior season is null on every row;
- both eligible-from fields are null on every row;
- all 15 numeric batter/pitcher prior features are null on every row;
- `batter_prior_missing` and `pitcher_prior_missing` are true on every row;
- no 2020 value or fabricated historical prior is present.

This correctly follows the source knowledge-time rule: the first available prior source season is 2021 and is eligible only from 2022. The builder's prior selection is fail-closed and never uses same-season priors (`server/sports_modeling/feature_view_gen3.py:157-182`).

The Phase 7 ablation fits medians only on each branch's development rows (`scripts/phase7_ablation.py:49-68,84-87`). No validation or sealed-season statistic determines a 2021 fill. Since 2021 contributes no finite prior values, A2's prior-feature medians are the same medians learned from its 2022–2023 rows; missing indicators retain the information that the 2021 priors were absent.

However, this is **not the preprocessing governed by the existing feature contract**. The frozen contract states fold-training-only **mean** imputation (`server/sports_modeling/feature_contract.py:372-380`), and `FoldPreprocessor` applies mean fill plus standardization (`server/sports_modeling/training.py:64-132`). Phase 7 uses median fill and no numeric scaling. Calling A0 the “current Gen-2 baseline” is therefore inaccurate: it is a new same-data comparator, not a replay of D3/C4 or the registered training policy.

Scientific interpretation:

- Including 2021 is honest if A2 is described as “additional context-only/prior-blind historical rows under a new, explicitly versioned preprocessing policy.”
- It is not a pure training-volume experiment at constant information coverage, because 181,732 of 547,808 A2 rows—about one-third—lack every prior feature.
- It is not a historical 2021 deployment replay because a real deployment would ideally have prior-2020 information.
- A2 should not replace A1 for logistic regression on current evidence: the independent paired analysis finds A2 materially worse than A1 on the already-used validation fold.

## 7. Base-feature parity

The repository harness's parity test is weaker than the report claims. It:

- inner-joins only overlapping IDs;
- uses only feature columns present in both frames;
- uses tolerant `np.isclose` rather than strict equality;
- does not test outer-key/cardinality equality, target identity, lineage, missingness, or types;
- records a failed result but does not abort the ablation (`scripts/phase7_ablation.py:117-145`).

The current artifact nevertheless passes a stronger independent check. After sorting/alignment by the natural PA key, the complete Gen-2 and Gen-3 overlap was compared with strict Arrow equality, ignoring only file metadata:

| Parity dimension | Compared | Exact mismatches |
|---|---:|---:|
| Row/key population | 549,479 | 0 missing; 0 extra; 0 duplicate |
| Full columns | 33 | 0 column/name/order mismatch after canonical alignment |
| Identity and lineage | all overlap rows | 0 |
| Target identity | all overlap rows | 0 |
| 22 base features | 12,088,538 feature cells | 0 |
| Missingness | all 33 columns | 0 |
| Arrow data types | all 33 columns | 0 |

`pyarrow.Table.equals(..., check_metadata=False)` returned true for the entire 549,479-row aligned table. Ordering independence was checked by key alignment rather than assuming physical order.

Conclusion: the **present bytes** have exact parity, stronger than the documented “0 feature mismatches.” The automated guardrail does not yet prove that property on a rebuild. The plan's “byte-identical” phrase (`docs/PHASE_7_ADVANCED_MLB_DATA_INTEGRATION_PLAN.md:112-117`) should be replaced by “strict row/column value parity” unless complete file bytes, compression, row groups, and metadata are also compared.

## 8. Leakage and A0/A1/A2 comparability

### Learned-step trace

| Step | Shipped Phase 7 behavior | Fold isolation | Finding |
|---|---|---|---|
| Feature set | Fixed 22 named base features | Not learned | Same across branches |
| Numeric imputation | Per-column development median | Development only | Leakage-safe, but not governed Gen-2 mean policy |
| Outlier policy | None | N/A | Same across branches; differs from some cockpit policies |
| Scaling | None | N/A | Same across branches; differs from governed `FoldPreprocessor` |
| Categoricals | Fixed one-hot domains for top/bottom, outs, base mask | Domains fixed a priori | Same 13 indicator columns |
| Feature selection | None | N/A | Same 22→32 design |
| Logistic | `C=1`, `lbfgs`, `max_iter=2000` | Fit on branch development only | Deterministic in this configuration; seed not explicit; convergence diagnostics not persisted |
| HGB | `max_iter=200`, `learning_rate=.1`, `random_state=20260819` | Main fit uses development only | sklearn auto early stopping reserves a random 10% development subset; policy is undeclared/non-temporal |
| External metric | Same class order and metric helper | Same 2024 rows only | Comparable conditional validation |

Across branches, target taxonomy, 22 source features, 32-column design, model-family definitions, external validation rows, metric definitions, and class order are the same. The main comparability limitations are:

1. **A0 identity:** it is not the governed Gen-2/D3/C4 pipeline. The governed raw 2024 logistic log loss is about 1.484255, versus Phase 7 A0 1.483693. The roughly 0.000562 pipeline difference is about half the claimed A1-vs-A0 improvement.
2. **A2 population:** missing-history coverage changes the scientific treatment, not merely sample size.
3. **HGB early stopping:** `early_stopping='auto'`, `validation_fraction=0.1`, and `n_iter_no_change=10` create a seeded random internal split with different absolute row counts by branch. This is not chronological and is omitted from result provenance.
4. **Convergence evidence:** logistic A1 used 1,944 of 2,000 LBFGS iterations. It completed without a warning but is close enough to the cap that `n_iter_` and warnings must be recorded and convergence should fail closed.

The experiment is therefore a valid **within-harness conditional comparison**, not a governed baseline replay and not a clean “row volume only” causal experiment.

## 9. Independent metric reproduction and uncertainty

### 2024 metrics, reproduced from 2021–2024-only input

| Branch/family | Dev rows | Log loss | Summed Brier | ECE10 | Top-1 | Macro-F1 | Effective iterations |
|---|---:|---:|---:|---:|---:|---:|---:|
| A0 logistic | 184,104 | 1.4836929667 | 0.7064384287 | 0.0126353463 | 0.4520167280 | 0.0880169801 | 1,737 / 2,000 |
| A1 logistic | 366,076 | 1.4825351719 | 0.7060511465 | 0.0033899050 | 0.4524935735 | 0.0862316372 | 1,944 / 2,000 |
| A2 logistic | 547,808 | 1.4827268478 | 0.7060989071 | 0.0030664930 | 0.4524935735 | 0.0863657771 | 1,773 / 2,000 |
| A0 HGB | 184,104 | 1.4880359157 | 0.7072550744 | — | 0.4517810457 | — | 32 / 200 |
| A1 HGB | 366,076 | 1.4862412070 | 0.7068552051 | — | 0.4521756765 | — | 58 / 200 |
| A2 HGB | 547,808 | 1.4856496602 | 0.7066220981 | — | 0.4519564371 | — | 57 / 200 |

Every independently recomputed log-loss value matches the persisted six-decimal result exactly. The independent logistic computation also reproduced Brier, ECE, top-1, and macro-F1 directly with NumPy rather than relying on the report. HGB was bounded to the same three fixed branches; no broad model tournament was run.

### Paired whole-game bootstrap

Prediction evidence was regenerated in memory for the three logistic branches from the filtered 2021–2024 input. The audit then resampled the 2,429 2024 games with replacement for 5,000 seeded paired replicates. Each replicate computes the plate-appearance-weighted mean log-loss difference over its resampled games, preserving within-game dependence.

Negative delta means the left branch has lower log loss and is better.

| Comparison | Observed delta | 95% percentile interval | P(left better) | Interpretation |
|---|---:|---:|---:|---|
| A1 − A0 | −0.001157795 | [−0.001344517, −0.000963277] | 1.000 | Stable but very small conditional gain |
| A2 − A0 | −0.000966119 | [−0.001191390, −0.000747565] | 1.000 | Stable but very small conditional gain |
| A2 − A1 | +0.000191676 | [+0.000109625, +0.000272640] | 0.000 | A2 is consistently worse than A1 |

Here `P(left better)` is the fraction of bootstrap deltas below zero.

The intervals exclude zero on this already-used 2024 fold, so the point ordering is not sampling noise at the game-cluster level. The practical effect remains small: A1 improves log loss by about 0.078% relative to A0, and A2 gives back part of that gain. This is conditional evidence from a validation season already used for model and branch selection; it is not fresh generalization evidence and must not be upgraded into a production claim.

No persisted Phase 7 prediction artifact, input-bound bootstrap manifest, or uncertainty result existed before this audit. The audit did not persist prediction rows because the mandate was read-only apart from this report.

## 10. Artifact identity, immutability, and retry safety

### What is present

The current reconciliation sidecar records season counts, prior coverage, quarantine counts, partition authority, bridge manifest, relative output path, physical output SHA, and build time (`server/sports_modeling/feature_view_gen3.py:192-200`; `scripts/phase7_build_gen3.py:90-99`). The current physical SHA matches the file.

### What is absent

Neither the Parquet nor an immutable manifest binds all of:

- dataset ID, version ID, manifest ID/SHA;
- exact source partition IDs and hashes;
- bridge artifact identity beyond a mutable sidecar field;
- target taxonomy and class order;
- feature schema and schema SHA;
- feature contract ID/SHA;
- temporal contract ID/SHA;
- code revision and dirty-tree state;
- Python/dependency environment;
- build run ID and creation time;
- canonical logical content SHA;
- row-level quarantine lineage.

The ablation result is weaker still. It is overwritten at a fixed path and omits input Parquet SHA, effective preprocessing contract, code/dependency identity, convergence state, HGB stopping state, predictions, explicit bootstrap evidence, and output content identity (`scripts/phase7_ablation.py:149-162`).

### Retry and corruption risk

The builder docstring says both “content-addressed” and “re-running overwrites the same output” (`scripts/phase7_build_gen3.py:1-6`). Only the second statement matches the implementation. Direct writes to the final Parquet and then to the final JSON provide no staging, file flush, atomic replace, lock, existing-content conflict check, or registry transaction. A crash can leave partial Parquet or a Parquet/sidecar mismatch; concurrent jobs are last-writer-wins.

The ablation trusts the fixed Parquet after checking only that it exists (`scripts/phase7_ablation.py:113-118`). It does not verify the recorded SHA before parsing, so a locally replaced same-schema file can generate apparently official results.

Required publication pattern:

1. Canonicalize and hash the complete Gen-3 schema, feature contract, temporal contract, source authorities, and logical rows.
2. Stage output in the destination filesystem, validate it, flush it, and atomically publish under `objects/sha256/<digest>/...`.
3. Reject an existing destination whose bytes or manifest diverge.
4. Register the immutable derived version transactionally.
5. Bind all experiment and prediction evidence to those identities plus code/environment/seed.

## 11. Platform compatibility

| Capability | Classification | Evidence |
|---|---|---|
| Materialized | **Pass — local scripts only** | Fixed runtime Parquet exists; builder at `scripts/phase7_build_gen3.py:82-99` |
| Registered | **Fail** | Read-only registry inspection found only the Gen-2 feature view; Phase 7 adds no registration path |
| Visible in Data Warehouse | **Fail for Gen-3** | Warehouse surfaces current registered dataset authority, not the local Gen-3 derived view |
| Selectable in Data & Population | **Fail** | UI has one hard-coded Gen-2 card/ID and persists selection as notes (`src/sports/cockpit/cockpitSteps1.tsx:205-295`) |
| Bound to experiment execution | **Fail** | `ExperimentConfig` has no project, dataset version, feature-view/content SHA, target, or temporal-contract identity (`src/sports/cockpit/cockpitApi.ts:160-167`) |
| Server-authorized | **Fail** | Cockpit resolves the Gen-2 glob and fixed season roles (`server/sports_cockpit/engine.py:54-70,165-203`; `server/sports_cockpit/modeling.py:516-531`) |
| Auditable | **Partial** | Present counts/hash/parent hints are useful, but mutable and incomplete |
| Immutable/retry-safe | **Fail** | Fixed-path direct overwrite with no atomic transaction |

The Phase 7 implementation report acknowledges that Data Warehouse/UX/server execution integration is deferred (`docs/PHASE_7_ADVANCED_MLB_CORPUS_IMPLEMENTATION_REPORT.md:104-115`). Accordingly, the current local materialization is not evidence that a scientist can select or execute Gen-3 through ASP.

There is an additional identity collision risk in the inherited cockpit: experiment identity is derived from model configuration, not dataset/feature-view/target/temporal/code authority (`server/sports_cockpit/modeling.py:620-689`). Pointing the backend at Gen-3 without repairing that identity could overwrite or masquerade as a Gen-2 experiment with the same model configuration.

## 12. Security and containment

### Phase 7 delta

No new router or network endpoint was added. No new secret, credential, unsafe pickle/joblib/model deserialization, `eval`, `exec`, subprocess shell, unsafe YAML, or application user-Python dependency was found. The only new deserialization formats are Parquet and strict JSON. The source package/bridge consumers reject malformed authorities and strongly constrain input paths. Raw/runtime data remains ignored by Git.

New Phase 7 security/governance findings:

| Severity | Finding | Consequence |
|---|---|---|
| P2 | Mutable, non-atomic fixed-path publication | Crash/concurrency/tampering can replace or desynchronize evidence |
| P2 | Ablation does not verify input SHA or bind provenance | Same-schema replacement can produce credible-looking unbound metrics |
| P2 | Builder bypasses the governed `BuiltFeatureView`/runner envelope and uses private readers/helpers | Derived output loses the second binding check, metadata, immutable identity, and registry transaction |
| P2 | Artifact estate is global, not project/tenant bound | No project authorization, retention, or tenant isolation before product use |
| P3 | Whole-file Arrow→Python→pandas/dense-matrix operations and `read_bytes()` hashing | Avoidable peak-memory/OOM risk on constrained jobs |
| P3 | Existing validation-to-use window when partitions are reread | A local concurrent replacement could race validation |
| P3 | Tests omit containment, tamper, atomicity, concurrency, and provenance cases | Green tests do not establish publication safety |

The fixed parameters and frozen source bound the present resource risk; it is not a remotely user-amplifiable denial-of-service path today.

### Inherited exposure that must be closed before Gen-3 server integration

The existing experiment retrieval route accepts an arbitrary `experiment_id` (`server/sports_cockpit/router.py:149-154`) and constructs a Windows path without an opaque-ID allowlist or resolved-boundary check (`server/sports_cockpit/modeling.py:755-759`). Because the forced suffix is `.json`, traversal can reach the new reconciliation and ablation JSON files under the shared runtime root. This sink predates Phase 7, but Phase 7 adds sensitive artifacts within its reach. Repair with strict ID validation plus resolved containment, preferably registry-backed lookup.

The inherited optional user-Python execution feature remains host execution when enabled (`server/python_execution.py:101-112,204-249,323-348`). Phase 7 does not rely on it, but an authorized user of that existing feature could read or alter global runtime artifacts. Do not expose Gen-3 on a shared host until that execution boundary and project authorization are appropriately isolated.

`.gitignore` is useful source-control hygiene; it is not access control, encryption, retention, immutability, or tenant isolation.

## 13. Tests and evidence quality

The focused Phase 7 suite passed 7/7. Its coverage is insufficient for the strength of the implementation report:

- five of seven tests skip when the local Parquet is absent (`tests/sports_modeling_phase7_gen3_test.py:20-24,49-105`);
- several tests trust mutable `gen3-reconciliation.json` rather than deriving facts from Parquet/source;
- the “builder population gate” test asserts a constant rather than exercising builder accept/reject behavior;
- no test binds sidecar SHA to Parquet bytes;
- no test checks strict outer-key/target/type parity or makes parity failure abort;
- no test checks actual A0/A1/A2 masks, preprocessing state, convergence, or no-default-scoring behavior;
- no test covers registration, UI selection, server authorization, atomic retry, interruption, concurrency, tampering, links/reparse points, or experiment identity;
- no prediction or uncertainty evidence is persisted.

The current artifact happens to pass stronger independent checks. Those checks need to become fail-closed, hermetic automated gates rather than relying on a particular developer runtime.

## 14. Blockers before advanced-data acquisition/integration

These are ordered gates. Large network acquisition may be separately researched, but its outputs must not be called authoritative ASP data until Gates 1–4 are complete.

### Gate 1 — Define and register Gen-3 authority

Create canonical, versioned Gen-3 feature, schema, target, knowledge-time, and temporal contracts. Give each a digest. Register the derived feature view against exact parent dataset/version/manifest, source partition IDs, bridge, code revision, environment, and row-level quarantine artifact. Explicitly authorize 2021–2022's transition from source “prior-only history” to derived development target rows.

### Gate 2 — Make publication immutable and atomic

Reuse the governed Gen-2 writer/runner design: staged write, validation, flush, atomic publication, content-addressed object path, link/reparse/hardlink checks, conflict rejection, and transactional registration. Make reconciliation and ablation evidence immutable children of the same authority.

### Gate 3 — Physically blind the sealed season

Default modeling and parity processes must load only authorized development/validation columns and rows. Remove optional sealed scoring from the ordinary comparison CLI or place it behind a separate one-shot authorization service and audit record. Tests must prove the forbidden season is absent from the in-memory comparison frame, not merely absent from fit masks.

### Gate 4 — Version a truthful preprocessing/experiment contract

Either run the established `FoldPreprocessor` and governed model policy, or explicitly version Phase 7's median/no-scale design as a new experiment. Persist fitted preprocessing, exact effective hyperparameters, class order, seeds, dependency versions, convergence/warnings, HGB internal stopping state, prediction evidence, and whole-game uncertainty. Do not label the present A0 a D3/C4 or current Gen-2 replay.

### Gate 5 — Strengthen parity and reconciliation tests

Require exact outer-key cardinality, identity, target, all authorized columns, missingness, types, and strict values; abort on any mismatch. Derive counts from source and output in hermetic tests, test builder behavior rather than constants, and persist a row-level quarantine ledger. Decide whether innings 15/16 belong in the Gen-3 schema.

### Gate 6 — Bind the platform end to end

Expose only registered server-resolved feature views; make Data Warehouse and Data & Population consume that catalog; embed immutable dataset/view/target/temporal identities in every experiment; and fail closed on stale or mismatched authority. Complete a lab→evaluation→registry identity test before scientist-visible use.

### Gate 7 — Close inherited host/runtime exposure

Repair experiment-ID path traversal and isolate or disable host Python execution for shared deployments. Add project/tenant ownership, least-privilege filesystem ACLs, encryption/retention policy, and tamper-evident access logs before server-authorized Gen-3 access.

### Gate 8 — Treat the data-value result proportionately

The A1 logistic gain is robust to game-cluster resampling on 2024 but only about 0.00116 log loss. A2 is worse than A1 for logistic, and HGB's monotonic point improvement uses undeclared random early stopping. Keep A1 as a research comparator, not a champion. Advanced feature families may be higher leverage, but their acquisition plan must include knowledge-time availability, identity reconciliation, license/terms evidence, immutable bronze manifests, rate/resource bounds, and predeclared B-family ablations before download begins.

## 15. Acceptance boundary and audit footer

Accepted now:

- the existence and internal structural correctness of the local Gen-3 base-feature materialization;
- exact source-row closure and natural-key integrity;
- honest prior-blind representation of 2021 in the materialized feature values;
- exact current-byte parity with Gen-2 on the complete 2023–2025 overlap;
- reproducibility of the reported 2024 A0/A1/A2 point metrics under the Phase 7 direct-script policy;
- the small conditional A1/A2 gains over A0, with A1 preferred to A2 for logistic on paired game-cluster evidence;
- non-modification of D3/C4, Gen-2, registered champions, and application code.

Not accepted now:

- “governed,” “content-addressed,” “immutable,” or “registered” descriptions of Gen-3;
- “sealed” as a claim of physical/default-process blindness;
- A0 as a replay of the governed Gen-2/D3/C4 baseline;
- a pure sample-volume interpretation of A2;
- scientist-selectable, server-authorized, shared-host, paid-pilot, regulated, or production use;
- beginning large authoritative acquisition before the identity/publication/blinding gates above exist.

Audit operations and restraint:

- Read-only source, Git, registry, manifest, Parquet, JSON, and SQLite inspection.
- Strict key/parity/reconciliation calculations.
- Six bounded fits only: the predeclared three branches × two existing families, with an explicit input-season assertion of 2021–2024.
- One bounded 5,000-replicate paired whole-game logistic bootstrap on 2024.
- Focused test only; no full suite that would intentionally score the protected season.
- No external download, broad model tournament, application-code change, artifact registration, promotion, D3/C4/Gen-2 mutation, commit, or push.
- No 2025 model fit, tuning, selection, prediction, metric, or bootstrap computation by this audit.
- The pre-existing untracked `GPT56_SOL_INDEPENDENT_ASP_AUDIT.md` was preserved unchanged.

The next acceptable state is not “add a Gen-3 card.” It is an immutable registered authority whose exact identity is selected by the server, propagated into execution, and recoverable from every result.
