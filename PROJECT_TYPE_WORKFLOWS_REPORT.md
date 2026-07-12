# Project Type Workflows Report

## Phase 16A A/B Testing Workflow

### Summary

Phase 16A builds the existing `A/B Testing` project type into a real experimentation workflow inside the current ATLAS project-type system. It does not add a separate A/B Testing Studio route. New A/B projects use `/workflow/ab-testing/:stepNumber`, the existing workflow rail, top progress bar, and standard project overview entry points.

### Dataset Used

The workflow is configured for the Kaggle Marketing A/B Testing dataset:

- Dataset: `AB_MARKETING.csv`
- Unit ID: `user.id`
- Treatment column: `test.group`
- Treatment value: `ad`
- Control value: `psa`
- Outcome column: `converted`
- Success event: `True`
- Exposure / intensity column: `total.ads`
- Segment columns: `most.ads.day`, `most.ads.hour`

The analysis helpers support string, boolean, and numeric success outcomes.

### Workflow Steps

The `A/B Testing` project type now uses this 15-step workflow:

1. Project Context
2. Experiment Setup
3. Population and Eligibility
4. Treatment / Control Design
5. Data Acquisition
6. Randomization Check
7. Metrics Setup
8. Power and Sample Size
9. Experiment EDA
10. Experiment Analysis
11. Segment Analysis
12. Business Impact
13. Decision Recommendation
14. Documentation Review
15. Monitoring / Follow-up

### Experiment Setup

The workflow captures experiment type, design, treatment, control, assignment unit, randomization unit, analysis unit, outcome window, exposure window, and experiment dates. Defaults are set for a user-level A/B test using `user.id`.

### Population and Eligibility

The workflow shows unique units, treatment and control group counts, treatment/control shares, and allocation imbalance warnings. The Marketing A/B sample intentionally flags the allocation imbalance because the `ad` group is much larger than the `psa` group.

### Treatment / Control Design

The workflow documents `test.group = ad` as treatment and `test.group = psa` as control, including descriptions, assignment method, actual allocation ratio, randomization notes, and contamination risk.

### Randomization Check

Randomization review includes sample sizes, allocation ratio, balance checks, exposure balance, segment balance, missingness balance, standardized mean difference expectations, and categorical/numeric test guidance. `total.ads` is explicitly labeled as exposure / intensity rather than a guaranteed baseline covariate.

### Metrics Setup

The default primary metric is conversion rate from `converted = True`, with secondary exposure review on `total.ads` and segment review by day and hour.

### Power and Sample Size

Binary-proportion power planning uses the observed control conversion rate as the baseline when available, then reports required per-group and total sample size against current treatment/control counts.

### Experiment EDA

The A/B workflow surfaces treatment/control counts, outcome distribution, conversion by group, allocation, exposure, segment sizes, missingness, and duplicate-unit checks.

### Experiment Analysis

The workflow calculates control and treatment conversion rates, absolute lift, relative lift, standard error, 95% confidence interval, two-proportion z-test p-value, statistical significance, and practical decision flags.

### Segment Analysis

Segment analysis renders day and hour segment examples with treatment count, control count, absolute lift, p-value, confidence interval, sample-size warning, and multiple-comparison options: Bonferroni, Benjamini-Hochberg FDR, or no correction.

### Business Impact

The workflow accepts rollout population, revenue per conversion, and cost per exposure assumptions, then reports incremental conversions, incremental revenue, incremental cost, net impact, and ROI direction.

### Decision Recommendation

Decision recommendations consider statistical significance, practical significance, sample size, randomization concerns, guardrails, segment effects, business impact, and governance notes. The UI explicitly states that it does not rely only on p-value.

### MEC Integration

Each A/B step exposes evidence actions:

- Save Evidence
- Open Model Evidence Center
- Attach to Model Documentation Studio
- Export Experiment Evidence Pack

Evidence types include experiment context, design, population eligibility, treatment/control definition, data quality, randomization check, metric definition, power analysis, EDA, analysis, segment analysis, business impact, decision recommendation, and monitoring plan.

### MDS Integration

The workflow maps experiment evidence to Model Documentation Studio sections including Business Purpose, Experiment Design, Population and Eligibility, Randomization Check, Metrics Definition, Experiment Analysis, Segment Analysis, Business Impact, Decision Recommendation, Limitations, Monitoring / Follow-up, and Appendices.

### Project Overview Integration

Project Overview now shows an A/B Testing Summary for A/B projects with experiment name, treatment, control, primary metric, treatment/control sample sizes, treatment/control conversion rates, absolute lift, relative lift, p-value, decision recommendation, allocation review, and evidence readiness.

### Tests Run

Local workspace validation:

- `npm run test:project-types` - passed
- `npm run test:experimentation` - passed
- `npm run test:evidence-graph` - passed
- `npm run test:model-documentation` - passed
- `npm run test:dataset-library` - passed
- `npm run test:persistence` - passed
- `npm run test:regression` - passed
- `npx tsc -b` - passed
- `npm run build:modeling` - passed
- `npm run build` - passed
- `npm run sync:atlas` - passed

Clean copy validation in `C:\Users\james\Projects\ATLAS\atlas-app`:

- `npm run test:project-types` - passed
- `npm run test:experimentation` - passed
- `npm run build` - passed

### Manual QA Results

Manual browser QA checklist for follow-up:

- Create `Marketing AB Test Workflow Demo`.
- Choose Project Type `A/B Testing`.
- Upload `AB_MARKETING.csv`.
- Confirm the A/B Testing workflow replaces the default predictive workflow.
- Confirm Unit ID, treatment column, treatment value, control value, outcome column, exposure column, and segment columns default correctly.
- Run Randomization Check and confirm treatment/control imbalance warning appears.
- Run Experiment Analysis and confirm conversion rates, lift, confidence interval, p-value, and significance render.
- Run Segment Analysis and confirm day/hour segments render.
- Enter business impact assumptions.
- Save evidence to Model Evidence Center.
- Open Model Documentation Studio and confirm experiment evidence is available.

This implementation pass was validated by static workflow tests, TypeScript, builds, and clean-copy checks. Full upload-driven browser QA remains dependent on the local `AB_MARKETING.csv` file being available in the browser session.

### Known Limitations

- The current workflow uses local deterministic Marketing A/B sample rows for default analytics until a full uploaded dataset artifact is connected to the A/B workflow page.
- Balance and statistical tests are surfaced with reviewable outputs and guidance; deeper backend statistical routines can be added after dataset-backed execution is connected.
- Evidence save uses the existing workflow node save path plus evidence export. A future phase can register richer typed MEC records per A/B evidence type.

### Recommended Next Build

- Connect the A/B workflow page directly to the Dataset Library artifact for `AB_MARKETING.csv`.
- Add backend-powered balance diagnostics for standardized mean differences, chi-square tests, and rank tests.
- Add downloadable CSV/PNG exports for A/B tables and charts.
- Add first-class MEC typed experiment evidence records instead of relying primarily on workflow node evidence.

### Acceptance Criteria

1. Selecting Project Type = A/B Testing loads a real A/B Testing workflow.
2. The Marketing A/B Testing dataset can be uploaded and mapped.
3. Treatment, control, outcome, unit ID, exposure, and segment columns are detected.
4. Randomization and allocation checks work.
5. Power and sample size analysis works.
6. Experiment analysis calculates lift, confidence interval, and p-value.
7. Segment analysis works.
8. Business impact and decision recommendation are available.
9. Evidence can be saved to MEC.
10. Documentation evidence can be mapped to MDS.
11. Clean copy is synced and builds.
