import assert from "node:assert/strict";
import fs from "node:fs";

const read = (path) =>
  fs.readFileSync(new URL(`../${path}`, import.meta.url), "utf8");

const step = read("src/steps/Step02_EDA.tsx");
const styles = read("src/components/eda/eda-premium.css");

const checks = [];
function check(name, callback) {
  try {
    callback();
    checks.push({ name, ok: true });
  } catch (error) {
    checks.push({ name, ok: false, error });
  }
}

function occurrences(source, marker) {
  return source.split(marker).length - 1;
}

check("the large shared hero is replaced by one compact EDA header", () => {
  assert.match(
    step,
    /title="Step 2: Exploratory Data Analysis"[\s\S]{0,300}\shideHeader/,
  );
  assert.equal(
    occurrences(step, 'data-testid="eda-compact-page-header"'),
    1,
  );
  assert.equal(occurrences(step, "heroMetrics="), 0);
  assert.match(styles, /\.eda-compact-page-header\s*\{/);
  assert.match(styles, /min-height:\s*58px/);
  for (const marker of [
    'data-page-identity="exploratory-data-analysis"',
    "eda-compact-title-lockup",
    "eda-compact-title-mark",
    "EDA intelligence workspace",
    "eda-compact-current-view",
  ]) {
    assert.ok(step.includes(marker), `Missing page-identity marker: ${marker}`);
  }
});

check("analysis tabs have one semantic, keyboard-visible contained rail", () => {
  assert.equal(
    occurrences(step, 'data-testid="eda-analysis-tab-rail"'),
    1,
  );
  assert.match(
    step,
    /<nav[\s\S]{0,180}aria-label="EDA analysis navigation"/,
  );
  assert.match(step, /role="tablist"/);
  assert.match(step, /role="tab"/);
  assert.match(step, /aria-selected=\{selected\}/);
  assert.match(
    styles,
    /\.eda-tab-rail \[role="tablist"\][\s\S]*border-radius:\s*10px/,
  );
  assert.match(
    styles,
    /\.eda-tab-rail \.atlas-tab-button:focus-visible[\s\S]*outline:\s*2px solid/,
  );
});

check("governed context is one strip with one authorization surface", () => {
  assert.equal(
    occurrences(step, 'data-testid="eda-governed-context-strip"'),
    1,
  );
  assert.equal(
    occurrences(step, 'data-context-panel="governed"'),
    1,
  );
  assert.equal(
    occurrences(step, 'data-testid="eda-predictor-authorization"'),
    1,
  );
  assert.doesNotMatch(
    step,
    /PredictorAuthorizationNotice/,
    "The former standalone authorization panel must not remain.",
  );
  for (const marker of [
    "Dataset / version",
    "Target",
    "Predictor manifest",
    "Documentation impact",
    "Backend enforced",
  ]) {
    assert.ok(step.includes(marker), `Missing compact context item: ${marker}`);
  }
});

check("verbose lineage, manifest, and documentation copy use one disclosure", () => {
  assert.equal(
    occurrences(step, 'data-testid="eda-governed-context-details"'),
    1,
  );
  for (const marker of [
    "Current tab documentation",
    "Dataset lineage",
    "Server-authorized predictor manifest",
    "Documentation state",
  ]) {
    assert.ok(step.includes(marker), `Missing disclosure content: ${marker}`);
  }
  assert.match(styles, /\.eda-context-details-panel\s*\{[\s\S]*position:\s*absolute/);
});

check("every tab has a compact quick-summary contract", () => {
  assert.equal(
    occurrences(step, 'data-testid="eda-tab-quick-summary"'),
    1,
  );
  for (const marker of [
    "Population",
    "Predictors",
    "Target balance",
    "Readiness",
    "Main review item",
    "Target lineage",
    "Prevalence",
    "Class balance",
    "Quality",
    "Selected predictor",
    "Missingness",
    "Monotonicity",
    "Strongest pattern",
    "Strongest pair",
    "Max VIF",
    "Review count",
    "Selected pair",
    "Time fields",
    "Time periods",
    "Segment fields",
    "Segments",
    "Availability",
    "Open",
    "Accepted",
    "Blockers",
    "Documentation state",
  ]) {
    assert.ok(step.includes(`label: "${marker}"`), `Missing summary item: ${marker}`);
  }
  assert.match(styles, /\.eda-tab-quick-summary\s*\{[\s\S]*min-height:\s*48px/);
});

check("active blockers remain visible outside the details disclosure", () => {
  assert.equal(
    occurrences(step, 'data-testid="eda-active-context-blocker"'),
    1,
  );
  assert.match(step, /role="alert"[\s\S]{0,160}aria-live="polite"/);
  const disclosureStart = step.indexOf(
    'data-testid="eda-governed-context-details"',
  );
  const blockerStart = step.indexOf(
    'data-testid="eda-active-context-blocker"',
  );
  assert.ok(
    blockerStart > disclosureStart,
    "The active blocker must be rendered independently of the disclosure.",
  );
});

check("sticky navigation and measurable first-content hooks enforce the budget", () => {
  for (const marker of [
    'data-testid="eda-compact-preamble"',
    'data-preamble-target-px="380"',
    'data-measured-preamble-px={',
    'data-preamble-budget-status={',
    'data-testid="eda-first-analytical-content"',
    'data-global-header-offset-px={stickyTopOffset}',
    '[data-testid="atlas-breadcrumb"]',
    'closest<HTMLElement>("header")',
    "ResizeObserver",
  ]) {
    assert.ok(step.includes(marker), `Missing preamble measurement hook: ${marker}`);
  }
  assert.match(
    styles,
    /\.eda-compact-sticky\s*\{[\s\S]*position:\s*sticky;[\s\S]*top:\s*var\(--eda-sticky-top,\s*7\.5rem\);[\s\S]*z-index:\s*19/,
  );
  assert.match(
    styles,
    /\.eda-compact-preamble\s*\{[\s\S]*gap:\s*0\.5rem/,
  );
  assert.match(
    styles,
    /@container eda-page \(max-width: 1050px\)[\s\S]*grid-auto-rows:\s*minmax\(29px,\s*auto\)/,
  );
});

check("compact context typography stays readable without spending height", () => {
  const compactStyles = styles.slice(0, styles.indexOf(".eda-section-band"));
  const remSizes = [...compactStyles.matchAll(/font-size:\s*([0-9.]+)rem/g)].map(
    (match) => Number(match[1]),
  );
  assert.ok(remSizes.length > 8, "Expected compact typography declarations.");
  assert.ok(
    remSizes.every((size) => size >= 0.625),
    `Compact text fell below 10px: ${Math.min(...remSizes)}rem`,
  );
  assert.match(
    compactStyles,
    /\.eda-context-item strong\s*\{[\s\S]*font-size:\s*0\.6875rem/,
  );
  assert.match(
    compactStyles,
    /\.eda-quick-summary-item strong\s*\{[\s\S]*font-size:\s*0\.6875rem/,
  );
});

check("Stability renders honest non-blocking capability previews when fields are absent", () => {
  for (const marker of [
    'data-testid="eda-stability-unavailable"',
    'data-analysis-available="false"',
    'data-confirmation-impact="non-blocking"',
    "Time trend",
    "Segment comparison",
    "Population drift",
    "Population Stability Index (PSI)",
    'data-capability-state="unavailable"',
    "governed observation-time or reusable segment field",
    "does not block",
    "No analysis fabricated",
  ]) {
    assert.ok(step.includes(marker), `Missing Stability marker: ${marker}`);
  }
  assert.match(
    step,
    /if \(!hasTimeFields && !hasSegmentFields\) \{[\s\S]{0,500}<StabilityUnavailableState/,
  );
  assert.doesNotMatch(
    step.slice(
      step.indexOf("function StabilityUnavailableState"),
      step.indexOf("function AnalysisSelectors"),
    ),
    /<CompactGroupTable|out_of_time_suggestion|event_rate/,
    "The unavailable state must not imply calculated stability output.",
  );
});

for (const [index, result] of checks.entries()) {
  console.log(`${result.ok ? "ok" : "not ok"} ${index + 1} - ${result.name}`);
}

const failures = checks.filter((result) => !result.ok);
if (failures.length) {
  for (const failure of failures) {
    console.error(`\n${failure.name}\n${failure.error?.stack ?? failure.error}`);
  }
  process.exitCode = 1;
} else {
  console.log(`\nedaCompactComposition.test.mjs: ${checks.length} checks passed.`);
}
