# Phase 6A — Interactive MLB PA Modeling Cockpit

## 1. Executive Verdict

**Status: `INTERACTIVE_MODELING_COCKPIT_VERTICAL_SLICE_READY`.**

Phase 6A delivers the first real, functional scientist-driven modeling workflow in ASP Model
Studio: a 15-step MLB plate-appearance modeling cockpit backed by a genuine science engine.
Every metric is computed from the materialized governed D3 feature view (549,479 PAs) and
evaluated with the frozen `server.sports_modeling` metrics authority — there is **no fabricated
result path**. The complete acceptance vertical slice runs end to end:

> open project → inspect target/data → profile predictors (IV/MI) → configure outlier policy →
> configure missing-value policy → select features → confirm temporal split → configure a
> Logistic Regression challenger → run it → evaluate 2024/2025 → compare against D3 → compare
> against Autopilot → test in the simulator (bounded whole-game Monte Carlo) → inspect
> game-level impact → save experiment evidence.

The cockpit's in-pipeline reproduction of the registered D3 champion (candidate C4) matches the
governed artifact within tolerance (2024 log loss **1.4841** reproduced vs **1.4843** registered),
which validates that cockpit challengers are numerically comparable to the champion of record.

## 2. Product Vision

ASP Model Studio is now a data scientist's workbench, not a black-box runner. The scientist
controls data → profiling → **outliers → missing values** → features → segmentation → temporal
split → models → hyperparameters → evaluation → calibration → simulation impact →
champion/challenger. Autopilot is a strong automated benchmark to compete against, not a
replacement for scientist control. The signature differentiator is answered directly: **does a
better PA metric actually improve the whole-game simulator?**

## 3. Workflow

`server/sports_cockpit/` (engine, modeling, simulation, router) + `src/sports/cockpit/`
(shell, API/store, UI primitives, 15 steps). Route `/pa-modeling-cockpit`; sidebar entry
"PA Modeling Cockpit". Canonical step order (enforced and tested):

01 Objective · 02 Data & Population · 03 Data Profile · **04 Outliers** · **05 Missing Values** ·
06 Feature Engineering · 07 Player Segmentation · 08 Temporal Split · 09 Model Laboratory ·
10 Hyperparameter Tuning · 11 Evaluation · 12 Calibration · 13 Simulation Impact ·
14 Champion / Challenger · 15 Registry.

**OUTLIERS strictly precede MISSING VALUES** (enforced in the step registry and asserted by
`tests/paModelingCockpit.test.mjs`).

Persistent context is always visible: dataset, target, champion, selected feature set, active
experiment, temporal policy.

## 4. Objective

Real objective payload: 8-class frozen target order, target distribution (BIP_OUT 45.0% …
TRIPLE 0.37%), prediction unit = PA, downstream use = whole-game simulator, registered champion
D3 C4 frozen evidence, editable research hypothesis (saved with the experiment context). The
frozen class order cannot be mutated without a new governed experiment.

## 5. Data & Population

Real governed counts per season (2023: 184,104 PAs / 2,430 games / 656 batters; 2024: 182,449;
2025: 182,926 · frozen). Population funnel, temporal policy chips, and honest known limitations
(debut-player prior gaps; no premium/umpire/weather/park in the free data).

## 6. Predictor Profiling

Every candidate predictor is profiled: dtype/kind, non-null, missing %, unique, min/max/mean/
median/std, percentiles, skew, IQR-outlier count, season-drift, one-vs-rest IV, MI. Cached
content-addressed on the feature-view content SHA (first build ~7s; instant thereafter).
Continuous / categorical / binary kinds are distinguished so meaningless metrics are not
computed for inappropriate types. A first-class sortable predictor-screening table with
include/exclude toggles (wired to the experiment feature set) and a per-feature detail drawer
(distribution, YoY, box, target-conditioned means, IV bins/event rates).

## 7. Information Value

Multiclass one-vs-rest IV: for each of the 8 outcomes, WOE/IV over **development-2023** bins
(continuous → deciles; categorical → categories), with MAX_IV, MEAN_IV, and the max-IV class.
IV correctly localizes signal (`batter_so_per_pa`→STRIKEOUT, `batter_hr_per_pa`→HOME_RUN,
`context_base_mask_before`→OTHER_REACH). The frozen 2025 season never participates in binning.
IV is presented as screening evidence, not automatic inclusion.

## 8. Mutual Information

`sklearn.mutual_info_classif` on a bounded development sample (≤30,000 rows), discrete-feature
mask per feature kind, surfaced side-by-side with IV so nonlinear signal invisible to univariate
IV is visible.

## 9. Outliers (before Missing Values)

Answers "how many outliers do we have?" first: total observations, features analyzed, features
with outliers, values flagged, % flagged, ranked by impact. Global methods: NONE / IQR /
ROBUST-Z (MAD) / STANDARD-Z / WINSORIZE, with a `k` control. **Side-by-side before/after
histograms** per treated feature (era9, whip, rates all show clear tail compression). Binary and
categorical variables are never capped. All thresholds are fitted **fold-local on development**
(FOLD-LOCAL PREPROCESSING badge). Preview until explicitly saved.

## 10. Missing Values

Comes after outliers. Answers "how much is missing?" first: features with missingness, total
missing values, rows affected, and missingness **by season**. Methods: NO IMPUTATION / MEDIAN /
MEAN / MOST FREQUENT / CONSTANT, plus an optional missing-indicator column. Fills are learned
fold-local on development. Real missingness is surfaced honestly (batter priors ~7.7%, pitcher
priors ~11.7% for debut players).

## 11. Feature Engineering

Selected feature-set manager (toggle chips, select-all / priors-only presets) and an honest
sports feature catalog: AVAILABLE governed families (game context, batter prior state, pitcher
prior state) plus a clearly-labeled roadmap (calendar, handedness/platoon, pitch-sequence E1 /
interaction E2, rest/workload, premium contact quality, umpire, weather, park, manager). No
unavailable calendar/premium metadata is fabricated. Custom arithmetic/interaction/calendar
construction is the next increment (honestly marked).

## 12. Player Segmentation

Exploratory workbench, explicitly `NEXT IMPLEMENTATION`. No clustering is silently injected into
the production PA model and no manual per-player boosts exist. The scoped design (K-Means /
Hierarchical / GMM with silhouette · Davies-Bouldin · Calinski-Harabasz, PCA, 3×3
Power×Contact / Dominance×Command grid, saved as a research feature set) is documented for 6B.

## 13. Temporal Split

Sports-native. Supported policies (Season holdout ·active, Rolling origin, Expanding window,
Date holdout, Random *with an explicit NOT-RECOMMENDED warning*). Fold timeline with row counts
and five enforced leakage guards (frozen-season protection, fold-local preprocessing, target
never a predictor, prior-season-only state, IDs excluded).

## 14. Model Laboratory

Honest algorithm cards from the backend: Logistic (multinomial), Random Forest, Extra Trees,
HistGradientBoosting, MLP, XGBoost, LightGBM (availability reflects the real install state —
all present), and Linear SVM (calibrated). Only Logistic is flagged SIM-READY (the Phase 5
whole-game replay requires the multinomial-logistic authority). Family-specific hyperparameter
controls, a "Use current D3 settings" preset, and a real **Run experiment** action that fits on
2023, evaluates 2024 & 2025 with the shared authority, and compares to the champion.

## 15. Hyperparameter Tuning

Manual + editable **grid search** over the logistic C grid, run on development/validation only,
ranked by 2024 log loss, with `FROZEN EVALUATION PROTECTED`. The best C is applied to the active
configuration. Tree/boosting grids are the next increment (honestly marked).

## 16. Autopilot

Bounded automated benchmark with QUICK / STANDARD / DEEP budgets (DEEP never auto-starts). QUICK
searches logistic candidates only; STANDARD adds HGB + RF; DEEP adds Extra Trees / deep HGB /
LightGBM. Produces a ranked candidate leaderboard (best, runner-up, per-candidate runtime and
2024/2025 metrics, honest failure status) and a first-class **My Model vs Autopilot vs Champion**
comparison. Selection uses 2024 validation only.

## 17. Evaluation

Champion-vs-challenger grouped bars (log loss / Brier / ECE) for 2024 and 2025; class-level
table (support, recall, class Brier, class ECE); row-normalized confusion heatmap; severe-miss
concentration (classes ranked by Brier contribution — no new expensive forensic run required);
family-appropriate feature influence (logistic |standardized coefficient|; tree importances).

## 18. Calibration

Top-label reliability curve and per-class reliability (predicted vs realized), ECE/Brier/balanced
accuracy, for 2024 and 2025. Calibration policy documented: NONE / TEMPERATURE (governed),
temperature fit on validation only, auto-rejected if it worsens the frozen-season Brier.

## 19. Simulation Impact (signature feature)

A **real bounded whole-game run Monte Carlo** reusing the governed Phase 5B base-out transition
authority. For a bounded sample of real games, outcomes are drawn per PA from the model's
probability vector and runs are drawn from the empirical base-out transition distribution at each
PA's real (outs, base) state, split by batting side into home/away score distributions. Champion
and challenger share the identical game sample, transition kernel, sim count, and RNG lineage, so
only the PA model differs. Reported: PA log loss/Brier, total-run bias/MAE/CRPS, run-diff MAE,
home-win Brier/log loss, 90% interval coverage. The 90% intervals are well-calibrated
(coverage ≈ 0.90–0.93) and home-win Brier (~0.19) beats a coin flip — evidence the run kernel is
sound. Verdict: `GAME_LEVEL_IMPROVEMENT` / `PA_ONLY_IMPROVEMENT` / `NO_MATERIAL_CHANGE` /
`GAME_LEVEL_DEGRADATION`. Budgets: Quick (40×150), Standard (90×250).

**Honest scope:** this is the QUICK actual-sequence marginal-state variant — it samples outcomes
at each game's real base-out states rather than evolving fully sampled lineups. The full
lineup-rotation whole-game simulator remains the Phase 5 research pipeline
(`scripts/run_mlb_whole_game_monte_carlo.py`); the cockpit mode is a bounded, reproducible impact
probe, not a replacement. Note: the Phase 5 `FastD3Fold` is hard-coupled to the 43-column dynamic
player-state layout, so it cannot accept arbitrary cockpit static-view challengers — the
transition-driven marginal-state MC is the honest, family-agnostic path.

## 20. Champion / Challenger

Champion of record (D3 C4) is never overwritten automatically; challengers remain research
status. A challenger ledger ranks all cockpit experiments by 2024 log loss. Promotion gates
(temporal integrity, fold-local preprocessing, target-never-a-predictor, 2024 improvement, 2025
frozen improvement, simulator impact reviewed, simulator non-degradation) are evaluated live from
the latest experiment and simulation.

## 21. Registry

Content-addressed cockpit experiment records under `.runtime/asp-model-studio/sports-cockpit/`
(ignored). A generated model card (objective, population, preprocessing, algorithm,
hyperparameters, metrics, vs-champion, status) and lineage/leakage-guard evidence, with logical
authorities rather than physical runtime paths.

## 22. Visual / UX Acceptance

Premium analytics-first design in the existing slate/cyan language: dark persistent context
header, grouped left step nav with completion dots, dense excellent tables (sortable, sticky
headers, virtual-friendly), and echarts visualizations (target distribution, histograms,
before/after pairs, calibration curves, confusion heatmap, grouped comparison bars, YoY lines).
Each page opens with data quickly, not paragraphs of preamble. Cockpit bundle is lazy-loaded
(404 KB gzip). **Protected browser QA is owner-deferred** (headless/authenticated environment);
verification relied on FastAPI TestClient end-to-end checks and focused integration tests.

## 23. Performance

Frame loaded once and cached; every transform vectorized NumPy/pandas — **no `iterrows`, no
per-row Python loops over the population, no repeated Parquet reloads** (the Phase 5G pathology is
avoided by construction). Profiling cached content-addressed. Champion baseline cached in-process.
Simulation actuals cached to disk after a single bounded play_transition pass. UI previews use
bounded samples; full compute is explicit and budgeted.

## 24. Security

No auth weakening; the cockpit router is mounted behind the same `require_user` dependency as all
sports routers. No unsafe expert execution was added. Experiment records are content-addressed and
confined to the ignored `.runtime` tree. No network/provider calls; no dataset acquisition.

## 25. Tests

- **Backend** `tests/sports_cockpit_test.py` — 16 tests: feature kinds / outlier eligibility,
  one-vs-rest development-only IV, MI bounds, real missing/outlier reporting, fold-local outlier
  bounds & preprocessor fit, missing indicator, champion C4 reproduction parity, experiment
  evaluation over both seasons + leakage guards, unknown-feature rejection, tree-family class
  alignment, honest family availability, bounded Autopilot budgets. **16 passed.**
- **Frontend** `tests/paModelingCockpit.test.mjs` — 10 tests: 15-step canonical order,
  **Outliers before Missing Values**, real endpoint wiring, no fake/mock path, Model Lab real run,
  simulation verdict wiring, honest unavailable states, temporal frozen protection, route/nav
  wiring, single shared experiment authority. **10 passed.**
- **Regression** — `sports_phase5_whole_game_mc`, `sports_phase5_base_out_transition`,
  `sports_dataset_phase4_scope`, `sports_dataset_pa_baseline_scope`: **49 passed** (no regression).
- TypeScript `tsc --noEmit` clean; `vite build` clean.

## 26. Known Limitations

- Simulation impact is the bounded marginal-state variant (see §19), not the full lineup-rotation
  Monte Carlo. Whole-game replay is logistic-only (Phase 5 FastD3Fold authority).
- Grid search and Autopilot deep budgets are wired for the logistic family in this slice; a
  general tree/boosting grid is the next increment.
- Player segmentation is an honestly-deferred exploratory design, not yet functional.
- Custom feature-expression engineering (arithmetic/interactions/calendar) is scoped for 6B.
- Browser QA owner-deferred; covered by TestClient + integration tests.

## 27. Phase 6B Priorities

1. Full lineup-rotation whole-game simulation impact for logistic challengers (reuse Phase 5
   harness), and a dynamic-state challenger path so richer families reach the simulator.
2. Custom feature engineering (arithmetic/ratios/interactions/logs/bins) + sports calendar
   features (day/week/month/All-Star/postseason/series-game).
3. Player segmentation workbench (K-Means/Hierarchical/GMM, silhouette/DB/CH, PCA, 3×3 grid),
   saved strictly as a research feature set.
4. General grid/random search across tree & boosting families with runtime/memory estimates.
5. Temperature-scaling calibration surfaced with before/after frozen-non-worsening enforcement.
6. Promotion to registered research champion (governed) and re-run/idempotent reuse UI.

---

### Feature Roadmap (to remain testable through the cockpit)
Calendar (day/week/month/All-Star/postseason) · umpire · weather · park · trade/environment ·
manager tendencies · handedness/platoon · catcher/battery · player archetypes ·
individual/hierarchical player effects · premium contact quality.

### Model Roadmap
Logistic · SVM · Random Forest · Extra Trees · XGBoost · LightGBM · Neural Network ·
hierarchical/Bayesian · multitask · ensembles. (Phase 6A ships logistic + RF + Extra Trees + HGB
+ MLP + XGBoost + LightGBM + calibrated Linear SVM; only logistic is simulator-eligible today.)

### Zero-confirmation ledger
bullpen feature work = 0 · new D3 retraining outside user-driven cockpit experiments = 0 ·
premium acquisition = 0 · live feeds = 0 · sportsbook integration = 0 · AISP access = no ·
financial ATLAS access = no · ds-workflow-starter access = no · provider/network calls = 0 ·
pushes = 0 · remote changes = 0.
