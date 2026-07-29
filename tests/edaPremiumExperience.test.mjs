import assert from "node:assert/strict";
import fs from "node:fs";

const read = (path) => fs.readFileSync(new URL(`../${path}`, import.meta.url), "utf8");

const step = read("src/steps/Step02_EDA.tsx");
const target = read("src/components/eda/TargetIntelligenceWorkspace.tsx");
const distribution = read(
  "src/components/eda/visual/PredictorDistributionExplorer.tsx",
);
const correlation = read("src/components/eda/visual/CorrelationExplorer.tsx");
const relationship = read(
  "src/components/eda/visual/RelationshipExplorer.tsx",
);
const relationshipWebGl = read(
  "src/components/eda/visual/RelationshipWebGL.tsx",
);
const vif = read("src/components/eda/visual/VifExplorer.tsx");
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

check("Overview is an analytical launch surface rather than a metric-card wall", () => {
  for (const marker of [
    'data-testid="eda-overview-launch-surface"',
    'data-testid="eda-dataset-fingerprint"',
    "governed readiness checks are clear",
    "Checks clear",
    "Predictor-type composition",
    'data-testid="eda-overview-population-balance"',
    'data-testid="eda-data-quality-health"',
    'data-testid="eda-overview-attention"',
    "What deserves attention",
    "Bureau special values",
    "Target-source exclusion",
    "Data Acquisition target:",
  ]) {
    assert.ok(step.includes(marker), `Missing Overview marker: ${marker}`);
  }
  assert.doesNotMatch(step, /readinessDeductions|readinessScore|0\.72|0\.68/);
  assert.ok(step.includes("constantColumns.length / predictors"));
  assert.ok(step.includes("invalidNumeric.length / predictors"));
  assert.match(step, /const configuredTarget = String\(data\.target/);
  assert.match(step, /data\.event_value/);
});

check("Target story consolidates identity, prevalence, uncertainty, and lineage", () => {
  for (const marker of [
    'data-testid="target-governed-lineage"',
    'data-testid="target-prevalence-story"',
    'data-testid="target-prevalence-ring"',
    'data-testid="target-uncertainty-guidance"',
    "RiskPerformance",
    "bad_flag",
    '"Bad"',
    '"Good"',
  ]) {
    assert.ok(target.includes(marker), `Missing target-story marker: ${marker}`);
  }
  assert.equal(
    target.match(/data-testid="target-event-rate"/g)?.length,
    1,
    "Event rate must have one primary prevalence presentation.",
  );
  assert.equal(
    target.match(/data-testid="target-event-count"/g)?.length,
    1,
    "Event count must have one primary prevalence presentation.",
  );
  assert.doesNotMatch(
    target.slice(target.indexOf("function Metric(")),
    /\btruncate\b/,
  );
});

check("Predictor IV is visible by default and tabular data is secondary", () => {
  assert.match(distribution, /const \[showIv, setShowIv\] = useState\(true\)/);
  assert.ok(distribution.includes('data-visible-by-default="true"'));
  assert.ok(
    distribution.includes(
      'data-testid="eda-distribution-accessibility-alternative"',
    ),
  );
  assert.ok(distribution.includes("Accessibility and export alternative"));
});

check("Correlation defaults to a full readable matrix with explicit modes", () => {
  assert.match(
    correlation,
    /useState<MatrixViewMode>\("readable"\)/,
  );
  for (const marker of [
    "Readable",
    "Compact",
    "Expanded matrix",
    "Auto-fit · Fit matrix",
    'data-default-vertical-scroll={',
    'data-scroll-boundary={',
    'data-matrix-height={dimensions.height.toFixed(0)}',
    'matrixViewMode === "compact"',
    'role="group"',
    'aria-roledescription="interactive correlation matrix"',
  ]) {
    assert.ok(correlation.includes(marker), `Missing matrix marker: ${marker}`);
  }
  assert.doesNotMatch(
    correlation,
    /matrixViewMode === "readable"[\s\S]{0,100}max-h-/,
    "Readable mode must not impose a fixed internal vertical viewport.",
  );
  assert.ok(correlation.includes(': "relative overflow-visible"'));
});

check("Relationship Explorer is first-class while WebGL stays lazy", () => {
  assert.ok(step.includes('data-testid="eda-relationship-explorer-section"'));
  assert.ok(step.includes("<React.Suspense"));
  assert.ok(step.includes("<RelationshipExplorer"));
  assert.doesNotMatch(step, /relationshipExplorerOpen/);
  for (const label of ["2D Scatter", "Density", "3D Explorer"]) {
    assert.ok(relationship.includes(label), `Missing relationship mode: ${label}`);
  }
  assert.match(
    relationship,
    /const RelationshipWebGL = lazy\(\(\) => import\("\.\/RelationshipWebGL"\)\)/,
  );
  assert.ok(relationshipWebGl.includes('from "echarts-gl/charts"'));
  const linkedPairEffect = relationship.slice(
    relationship.indexOf("useEffect(() => {\n    if (initialPair)"),
    relationship.indexOf("useEffect(() => {\n    if (initialPair) return;"),
  );
  assert.doesNotMatch(
    linkedPairEffect,
    /\baxes\.x\b/,
    "The initial heatmap pair must not reapply when a user changes X.",
  );
});

check("Documentation, confirmation, and duplicate-decision slots are visible", () => {
  for (const marker of [
    'data-testid="eda-documentation-impact"',
    'data-testid="eda-confirmation-status"',
    'data-testid="eda-duplicate-decision"',
    "duplicateTreatment",
    "duplicateDecisionSavedAt",
    'aria-live="polite"',
    'aria-atomic="true"',
  ]) {
    assert.ok(step.includes(marker), `Missing documentation marker: ${marker}`);
  }
});

check("Primary VIF analysis expands with the page instead of nesting scroll", () => {
  assert.ok(vif.includes('data-default-vertical-scroll="false"'));
  assert.doesNotMatch(vif, /max-h-\[620px\][^"]*overflow-y-auto/);
});

check("Motion is purposeful and has a reduced-motion fallback", () => {
  for (const marker of [
    "@keyframes eda-tab-enter",
    "@keyframes eda-grow",
    "@keyframes eda-ring-enter",
    "@media (prefers-reduced-motion: reduce)",
    "animation: none !important",
  ]) {
    assert.ok(styles.includes(marker), `Missing motion marker: ${marker}`);
  }
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
  console.log(`\nedaPremiumExperience.test.mjs: ${checks.length} checks passed.`);
}
