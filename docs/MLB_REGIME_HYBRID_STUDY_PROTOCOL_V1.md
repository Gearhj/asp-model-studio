# MLB regime / hybrid study v1

Status: pre-execution design. Research only, no promotion or wagering authority.

## Authority and hard boundaries

User reconciliation on 2026-09-10 selects accepted V18, not the earlier Gen3
temporal authority. Preserve the exact ordered target:
STRIKEOUT, WALK_HBP_CI, HOME_RUN, SINGLE, DOUBLE, TRIPLE, BIP_OUT, OTHER_REACH.
Use V18 specification stage3-feature-treatment-spec-711fbb376e9a4d419f826de593195638,
manifest 4d158e01a4a7d84fe6e7641f61edf0e9848f1775e025a2cec6c29cda22d479f3,
its 273 treated inputs, original eligibility hold and saved chronological folds.
The registered Final OOT, 2026-08-14 through 2026-08-27, remains physically unread.
Do not hash or read a mixed Development/OOT payload to authenticate a source.
Read footer metadata first and only wholly Development row groups. If necessary,
exclude the entire boundary date to retain game-atomic comparisons. Publish the
exact resulting coverage loss; never relabel partial reproduction as full coverage.

Baseline reproduction must pass before challenger development. Compare frozen
estimator outputs to saved OOF on exact canonical PA IDs, preserving class order
and recording bitwise equality and floating-point differences separately. The
accepted wrapper's normalization must not be misreported as model disagreement.
No baseline refit. Every source restriction and semantic treatment remains in force.

## Chronological design

- 2023 (fold 1 training): fit clustering transforms and archetypes. Choose between
  two or three broad groups using earlier/later 2023 training-era stability,
  interpretable profiles and minimum population support, never later test loss.
- Folds 1 and 2 OOF (2024-03-20 through 2025-04-15): discover persistent failure
  regimes. The production study archetypes are frozen from 2023, so no observation
  chooses its own cluster centers. Additional training-era refits only measure
  stability and do not retroactively change the assigned labels.
- Fold 3 OOF (2025-04-16 through 2025-07-27): fit forecast-correction layers against
  genuinely out-of-fold V18 errors. Keep the accepted HGB models frozen. Every
  comparator shares the same rolling global probabilities and update schedule.
- Fold 4: divide ordered unique game dates 50% / 25% / 25%. First segment fits
  regularized gates and ensemble weights, second fits scalar chronological
  temperature calibration, last selects a frozen candidate. Report each role;
  training or selection results are not independent evaluation results.
- Fold 5 (2026-05-02 onward, ending at the last physically safe complete date):
  evaluate every frozen candidate and the selected architecture. Do not refit,
  select weights, redefine regimes or retune after viewing these results.

All folds are game atomic. Fold 5 is a later Development comparison, not a new
untouched holdout: it was already used in prior V18 research. No claim of independent
Final OOT success can follow from this study.

## Bounded architectures

Compare PCA plus regularized Gaussian mixture with robust-scaled centroid
clustering, not an algorithm sweep. Use governed finite channels for batter process,
pitcher process, team rest/travel and pre-event matchup/calendar contexts. Retain
soft memberships and support checks. Missing-domain rows get no specialist
influence, not a generic median/mode. A rest/travel cluster is not bullpen availability.
Unavailable roster, manager, defense, weather-vintage and ABS behavior evidence is
explicitly unavailable, not invented or inferred from realized outcomes.

Evaluate at most these five distinct systems, always retaining V18 as fallback:

1. Multinomial ridge correction with log V18 probability as a fixed offset and
   cluster memberships as covariates. This augments the probability forecast, not
   the HGB input schema; do not describe it as a refitted global tree model.
2. The same offset architecture with predeclared batter/pitcher membership
   interactions and platoon interaction covariates.
3. V18 plus shrunken, qualified cluster residual corrections.
4. V18 plus those same experts under a regularized soft gate.
5. A convex ensemble including one genuinely different existing global model's
   matching OOF, if its target, dates and identities reconcile. A different treatment
   version of the same HGB is not by itself a different model family.

At most two offset-model fits; no global estimator fits or hyperparameter search.
This pre-fit refinement avoids comparing stale augmented HGBs to a rolling V18
baseline. The fitted coordinates must be semantic fields, never fold-dependent
arbitrary category integers. Keep four native workers and log actual fit starts
and completions separately.
Residual experts must have adequate effective sample size and games, repeat across
at least two seasons with stable signed class residuals, and have a pre-event
definition. Select a maximum of four persistent regimes before specialist fitting.
Shrink class residuals toward zero, cap per-class probability adjustments, taper
outside observed support and preserve a valid eight-class simplex. State exact
regularization and support constants in the executable frozen contract before fits.

Predeclared numerical choices: seed 20260910; at most 30,000 deterministically
sampled complete domain rows per clustering fit; PCA retains 90% training variance;
mixture covariance regularizer 0.05, diagonal covariance, one initialization;
robust centroid comparator uses three initializations. Compare k=2 and k=3 on
2023-only chronological prefix/late-training assignments. Require at least 5%
training mass per cluster and prefer stability, then the smaller k. Features use
named semantic values; unobserved domain values produce zero membership/support.
Support tapers beyond the training 99th percentile distance and reaches zero at
twice that distance. No missing-value imputation is added.

Persistent-regime discovery requires at least 1,000 effective PAs and 100 games
per represented season, at least two seasons, consistent signed class residuals
across seasons and the two discovery folds, and absolute residual at least 0.003
per season. Rank by the weakest-season absolute residual and retain at most four
distinct domain/cluster regimes. This is discovery, not a formal significance test.
Residual shrinkage uses 10,000 zero-residual pseudo-observations and caps absolute
class corrections at 0.03. A simplex-preserving line search scales a correction
down if necessary; do not drop or manufacture probability mass.

Membership/interaction offset coefficients use a 0.01 L2 penalty on mean loss;
center covariates using fold 3 means to separate regime effects from global bias.
Include an explicitly labeled global class-offset control with the same fit dates.
All correction branches retain at least 50% global mixing weight and a 0.03 maximum
per-class movement. Soft expert gates retain at least 75% global weight; gate and
ensemble regularization is 0.01 toward no correction / V18. Calibrators use one
scalar temperature bounded to [0.75,1.5], fitted only on the calibration segment;
apply the same opportunity to V18 and every comparator. Report raw and calibrated
results separately. These constants are fixed research capacity/support constraints,
not optimized wagering thresholds or claims of empirically justified business limits.

Clustering execution additionally requires at least 1,000 complete rows per 2023
prefix/late-training segment. KMeans soft-membership temperature is the training
median positive nearest squared distance (a distance scale, not missing-value
imputation). Soft-gate coefficient shrinkage targets the support-proportional neutral
gate, with an explicit 75% global floor, rather than claiming coefficients of zero
eliminate all expert influence. Fit objectives use the same capped probabilities
that prediction returns.

Selection uses only fold 4's last segment: the lowest calibrated log loss among
candidates whose Brier does not exceed calibrated V18. Freeze that identity before
fold 5 evaluation. The global class-offset control diagnoses recalibration-only
benefits. To recommend further independent evaluation, require negative final-fold
log-loss difference, nonworse Brier, game and calendar-block intervals excluding
zero, and improvement in a majority of evaluated calendar months. Inspect calibration
and removal sensitivities before making a claim; incomplete pregame game evidence
still prevents a whole-game forecasting claim. These are research advancement rules,
not policy/staking criteria.

## Evaluation and inference

Report log loss, multiclass Brier, class-wise reliability/intercept/slope, rare
classes, entropy/sharpness, exposure/cold-start and domain regimes. Show in/out-of-
regime performance, influence rates and average/max probability adjustments.
Report ablations excluding the strongest cluster, month and team as sensitivity
analyses, not independent new discovery opportunities.

Use paired loss differences on exact common IDs. Report game-cluster and moving
calendar-week block bootstrap intervals plus repeated batter/pitcher/team cluster
sensitivity where identity evidence exists. These address different dependence
structures; do not imply one clustering accounts for all dependence. Use a fixed
seed and 1,000 replicates. Missing identities yield explicit unavailable intervals.
Exploratory multi-candidate intervals are not multiplicity-adjusted promotion tests.

Use unchanged base/out simulation and common random numbers. Historical realized
participants or game-local PA averages permit only oracle/mechanics sensitivity.
Never label that pregame skill. Report run distributions, moneyline/run/total/margin
and coverage diagnostics only with clearly identified truth and scope. Lack of
historical announced-at participant or paired pregame market timestamps limits
those comparisons, not the PA-level study.

## Completion

Content-address results, assignments, error atlas, fitted study objects and reload
checks, comparison tables, evidence limitations and forward AISP join contract.
Create the requested editable cluster-review workbook and a concise registered
Model Studio analytical view. At most one frontend build; focused tests only.
Publish current shadow predictions only if the selected candidate improves the
total system, calibration/regime stability remain supportable, and existing current
PIT evidence satisfies its exact input schema. Otherwise publish a forward contract
without forecasts. Never change official forecasts or AISP policy/persistence.

Scientific outcome: retain V18, preserve a research challenger, or request separately
authorized Final OOT. No champion declaration or automatic promotion.
