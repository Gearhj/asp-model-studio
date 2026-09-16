# MLB V19 bounded research declaration

Frozen before new candidate fits or candidate evaluation. Starting authority:
`9b6253fa7c59ebf5d19a3c1fb1b220efd7fc14f4`. V18 remains retained.

## Population and information boundary

Use the five accepted chronological V18 folds and exact eligible PA IDs in the
physically Development-only baseline cache, ending 2026-08-06. Its 494,432 OOF
rows are the common comparison population; 7,107 other registered eligible OOF
rows remain excluded because reading them would cross the physical seal or an
incomplete boundary date. Preserve the 56-observation eligibility hold. Preserve
the eight classes including WALK_HBP_CI and OTHER_REACH. No Final OOT access.
These Development periods have been studied before: results and intervals are
research evidence, not an independent confirmatory trial.

New historical priors use only earlier game dates (exclude the entire current
date, including doubleheaders), with hyperparameters fitted inside the outer
training prefix. This is a conservative chronological reconstruction under the
accepted Development source contract, not proof of historical publication
vintages. Newly retrieved operational workload/roster evidence is forward-only
unless original historical availability is established. Never move it into the
historical matrix merely because the underlying game was historical.

## Fixed matrix and fit budget

1. V18: replay the corresponding saved estimator and fitted preprocessor exactly.
2. SEMANTIC_HGB: retain V18's HGB architecture and 500 iterations, adding
   training-fitted hierarchical class-composition priors for batter, pitcher,
   batting team and fielding team. Retain the corresponding frozen V18 treatment.
3. SEMANTIC_EXTRA_TREES: one new 240-tree model, max depth 20, minimum leaf 50,
   max_features 0.7, no bootstrap, no class reweighting. This is not the missing
   historical RF. Use the same semantic inputs and frozen categorical encoding.
4. REGIME_HGB: the same HGB plus fixed pregame regime indicators. This is the
   global regime-indicator control.
5. REGIME_CLUSTER_HGB: add training-only clusters to REGIME_HGB, isolating the
   incremental contribution of clustering with all other settings unchanged.
6. GLOBAL_ENSEMBLE: convex mixture of the four new global predictions and V18,
   fitted using only earlier chronological OOF predictions.
7. SPECIALIST_MIXTURE: at most two pregame-regime class-offset specialists on
   V18, with partial pooling and a convex gate fitted on disjoint earlier OOF
   segments. If insufficient persistent regimes exist, this is the identity V18
   branch, not an invented specialist.

Twenty global estimator fits maximum (four per fold); no parameter grid or
replacement family. Fixed seeds 20260911 + fold number. Four native workers per
fit, one global fit at a time. Failed fits are recorded, not silently retried.
Prediction chunking and deterministic summation are implementation details,
not alternative models. Persist every fold's complete executable dependencies
and exact reload fixture before advancing to another fold.

## Priors, clusters and specialists

Class-count priors distinguish retained historical exposure from no observation.
League/handedness population probabilities and concentration are training-only.
Previous-season carryover decay is estimated from training prequential loss when
multiple seasons identify it; otherwise it is explicitly unestimated. No global
median/mode fill. Uncertainty-only posterior dispersion is kept outside the
score-mean feature matrix and is tested for mean invariance. Exposure/reliability
inputs are intentionally mean predictors, not mislabeled uncertainty-only fields.

Use one fixed three-cluster KMeans architecture per supported domain, with
training-only standardization, deterministic outcome-independent sample caps,
and missing-domain exclusion. Batter, pitcher role propensity, team offense,
team defense, schedule/travel and matchup coordinates are permitted. Annual
GS/G is historical role propensity, not a current starter declaration. Bullpen
availability clusters require evidence; do not manufacture them. Compare
prefix/subprefix membership stability and report drift without choosing the
architecture from validation results.

Candidate regimes are defined from pregame fields only. A specialist can be
eligible only after at least two earlier OOF folds each support 2,000 PAs and
100 games, stable excess loss (at least 0.01 versus complement) or consistent
class residual direction, and pooled coverage of at least three months and ten
teams. Select at most two by prior-only excess-loss rank. Freeze eligibility
before reading that fold's candidate results. The first two folds therefore
have no specialist. No routing from realized inning, outs, bases or score.

Meta fitting uses the earliest 70% of available prior-OOF game dates; the next
15% fits ensemble/specialist gates and the final 15% fits scalar temperatures.
No meta fit is allowed without an earlier OOF prefix. Fold 1 uses identity
calibration and V18-only mixture. Raw and equally chronological calibrated
outputs are both reported; no candidate receives evaluation-fitted calibration.

## Predeclared decision rule

A research challenger must improve matched calibrated log loss with nonworse
Brier, improve in at least three of five chronological folds, and have both
paired game-clustered and four-week-block descriptive 95% intervals below zero
for log-loss difference. It must retain improvement after separately removing
its strongest month, team, cluster and supported regime. Report the result even
when it fails. No wagering/promotion implication follows from passing.

A specialist additionally must improve its routed population, show no positive
point-estimate log-loss or Brier harm in the complement, and improve multiple
eligible future folds. It must beat the global regime-indicator control to
justify separate specialist complexity. Insufficient subgroup support is not
success. Early-season/cold-start and per-class results remain explicit.

Game-level claims require genuine pregame inputs and compatible outcomes.
Realized-PA-inventory simulation is a separately labeled mechanics sensitivity
only. Do not use it to claim winner/score forecasting superiority. Market results
require contemporaneous timestamp-compatible evidence; the prior 40-game result
is not confirmation. Final OOT remains sealed regardless of Development rank.

## Delivery and operation

All new code/artifacts use the V19 research namespace. Do not edit the pinned
deployment, current V18 objects, AISP, NFL/NBA, policies or authority. A candidate
is publishable only after full fitted assets reload exactly and current inputs
are genuinely available before cutoff. Otherwise report exact skips and preserve
an executable research package without issuing a fabricated current forecast.
Include an editable review workbook, source audit, failure atlas, metrics,
checksums, actual fit accounting and explicit source limitations.
