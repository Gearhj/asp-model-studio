import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

const read = async (path) =>
  (await readFile(new URL(`../${path}`, import.meta.url), "utf8")).replace(
    /\r\n/g,
    "\n",
  );

const [
  step,
  modelingApp,
  styles,
  landscape,
  secondary,
  lazySecondary,
  visualData,
  distribution,
  motion,
  performanceSource,
  documentationPanel,
  documentationApi,
  documentationService,
  packageSource,
  premiumE2e,
] = await Promise.all([
  read("src/steps/Step02_EDA.tsx"),
  read("src/apps/ModelingApp.tsx"),
  read("src/components/eda/eda-premium.css"),
  read("src/components/eda/visual/PredictorSignalLandscape.tsx"),
  read("src/components/eda/visual/PredictorSecondaryInsights.tsx"),
  read("src/components/eda/visual/LazyPredictorSecondaryInsights.tsx"),
  read("src/components/eda/visual/predictorVisualData.ts"),
  read("src/components/eda/visual/PredictorDistributionExplorer.tsx"),
  read("src/visual-intelligence/motion.ts"),
  read("src/visual-intelligence/performance.ts"),
  read("src/components/documentation/EdaDocumentationLiveLink.tsx"),
  read("src/lib/edaDocumentationApi.ts"),
  read("server/eda/documentation_service.py"),
  read("package.json"),
  read("tests/e2e/eda-premium-experience.spec.ts"),
]);

const occurrences = (source, value) => source.split(value).length - 1;

test("1. compact governed-context strip has the required identity and state", () => {
  assert.equal(occurrences(step, 'data-testid="eda-governed-context-strip"'), 1);
  for (const label of [
    "Dataset / version",
    "Target",
    "Predictor manifest",
    "Documentation impact",
    "Backend enforced",
  ]) {
    assert.match(step, new RegExp(label));
  }
  assert.match(step, /data-testid="eda-governed-context-details"/);
});

test("2. first analytical content is measured against the 380px budget", () => {
  for (const marker of [
    'data-testid="eda-compact-preamble"',
    'data-testid="eda-first-analytical-content"',
    'data-preamble-target-px="380"',
    "data-preamble-budget-status",
    "ResizeObserver",
  ]) {
    assert.match(step, new RegExp(marker.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")));
  }
  assert.ok(
    step.indexOf("<PredictorSignalLandscape") <
      step.indexOf("<PredictorDistributionExplorer"),
  );
});

test("3. governed context is not duplicated and restoration detail is collapsed", () => {
  assert.equal(occurrences(step, 'data-context-panel="governed"'), 1);
  assert.equal(occurrences(step, 'data-testid="eda-predictor-authorization"'), 1);
  assert.equal(occurrences(step, 'data-testid="eda-documentation-impact"'), 1);
  assert.match(modelingApp, /data-testid="eda-compact-restoration-details"/);
  assert.doesNotMatch(modelingApp, /data-testid="eda-compact-restoration-details"[^>]*\sopen/);
});

test("4. Predictor Signal Landscape is bounded, interactive, and explanatory", () => {
  assert.match(landscape, /data-testid="predictor-signal-landscape"/);
  assert.match(landscape, /data-landscape-mark/);
  assert.match(landscape, /role="button"/);
  assert.match(landscape, /tabIndex=\{0\}/);
  assert.match(landscape, /Which predictors stand out/);
  assert.match(visualData, /PREDICTOR_VISUAL_MAX_MARKS = 60/);
});

test("5. predictor selection synchronizes through the shared visual store", () => {
  for (const source of [landscape, secondary]) {
    assert.match(source, /useEdaVisualSelection/);
    assert.match(source, /setSelectedVariable/);
  }
  assert.match(distribution, /selectedVariable/);
  assert.match(step, /data-selected-predictor=/);
  assert.match(step, /data-testid="eda-linked-selection-summary"/);
});

test("6. Predictor Quality Matrix exposes normalized and raw comparable values", () => {
  assert.match(secondary, /data-testid=\{testId\}/);
  assert.match(secondary, /testId="predictor-quality-matrix"/);
  assert.match(secondary, /data-quality-cell/);
  assert.match(secondary, /normalizedValue/);
  assert.match(secondary, /Accessible quality matrix table/);
  for (const control of ["Filter predictors", "Sort rows", "Review-heavy only"]) {
    assert.match(secondary, new RegExp(control));
  }
});

test("7. Event-Rate Shape Gallery is bounded and compares against baseline", () => {
  assert.match(secondary, /testId="event-rate-shape-gallery"/);
  assert.match(secondary, /data-event-shape-line/);
  assert.match(secondary, /strokeDasharray="4 3"/);
  assert.match(secondary, /weightedBaseline/);
  assert.match(visualData, /PREDICTOR_GALLERY_MAX = 10/);
});

test("8. Missingness map separates null, bureau-special, and ordinary values", () => {
  assert.match(secondary, /testId="missingness-special-value-map"/);
  for (const label of [
    "Ordinary in-range values",
    "Ordinary numeric outliers",
    "Null missingness",
    "Bureau special values",
  ]) {
    assert.match(secondary, new RegExp(label));
  }
  assert.match(secondary, /mutually exclusive/i);
});

test("9. all new visuals exclude target and deterministic target sources", () => {
  assert.match(visualData, /ALWAYS_EXCLUDED = new Set\(\["bad_flag", "riskperformance"\]\)/);
  assert.match(visualData, /\.\.\.\(input\.targetSourceExcluded \?\? \[\]\)/);
  assert.match(visualData, /authorized\.has\(normalizedFeature\)/);
  assert.match(visualData, /excluded\.has\(normalizedFeature\)/);
});

test("10. predictor visuals consume one batched aggregate response", () => {
  const visualSources = landscape + secondary + lazySecondary + visualData;
  assert.doesNotMatch(visualSources, /\bfetch\s*\(/);
  assert.match(visualData, /single_batched_workspace_request/);
  assert.match(secondary, /data-aggregate-boundary="single-batched-predictor-response"/);
  assert.match(step, /predictor_visual_shape_limit: 8/);
});

test("11. lower-page predictor insights are code- and viewport-lazy", () => {
  assert.match(lazySecondary, /\blazy\(/);
  assert.match(lazySecondary, /IntersectionObserver/);
  assert.match(lazySecondary, /rootMargin: "360px 0px"/);
  assert.match(lazySecondary, /data-load-state=/);
  assert.match(lazySecondary, /"deferred"/);
});

test("12. predictor motion respects reduced-motion preferences", () => {
  assert.match(landscape + secondary, /useReducedMotion/);
  assert.match(landscape + secondary, /runAtlasD3Transition/);
  assert.match(motion, /reducedMotion/);
  assert.match(styles, /@media \(prefers-reduced-motion: reduce\)/);
});

test("13. all three supported viewport layouts are specified", () => {
  for (const viewport of ["1366x768", "1536x864", "1920x1080"]) {
    assert.match(premiumE2e, new RegExp(viewport));
  }
  assert.match(styles, /@container eda-page \(max-width: 1050px\)/);
  assert.match(styles, /@container eda-page \(max-width: 760px\)/);
});

test("14. EDA confirmation uses the governed authenticated API", () => {
  assert.match(step, /confirmEdaDocumentation/);
  assert.match(step, /Confirm EDA and Continue/);
  assert.match(step, /confirmation_id/);
  assert.match(documentationApi, /credentials: "include"/);
});

test("15. MDD renders the immutable approved EDA state and its lineage", () => {
  assert.match(documentationPanel, /approved-eda-documentation-title/);
  for (const label of [
    "Project ID",
    "Dataset ID",
    "Dataset Version",
    "Target",
    "Predictor manifest",
    "Documentation version",
    "Confirmation ID",
    "Confirmed by",
  ]) {
    assert.match(documentationPanel, new RegExp(label));
  }
});

test("16. an upstream EDA change exposes a stale approved state", () => {
  assert.match(documentationPanel, /Stale after upstream change/);
  assert.match(documentationPanel, /Reconfirmation required/);
  assert.match(documentationApi, /invalidateEdaDocumentation/);
});

test("17. MDD keeps draft changes separate from approved content", () => {
  assert.match(documentationPanel, /approved-eda-documentation-title/);
  assert.match(documentationPanel, /draft-eda-documentation-title/);
  assert.match(documentationPanel, /Not approved/);
  assert.match(documentationPanel, /Preserved/);
  assert.match(documentationPanel, /findChangedSections/);
});

test("18. confirmation writes are idempotent and history records stay unique", () => {
  assert.match(documentationService, /idempot/i);
  assert.match(documentationService, /confirmation_id/);
  assert.match(documentationPanel, /key=\{`\$\{item\.confirmation_id\}-\$\{index\}`\}/);
});

test("19. browser acceptance records uncaught page and console errors", () => {
  assert.match(premiumE2e, /page\.on\("pageerror"/);
  assert.match(premiumE2e, /message\.type\(\) === "error"/);
  assert.match(premiumE2e, /expect\(pageErrors\)\.toEqual\(\[\]\)/);
});

test("20. the repository retains its complete security-gate command", () => {
  const pkg = JSON.parse(packageSource);
  assert.equal(pkg.scripts["test:security"], "python scripts/run_security_tests.py");
});

test("instrumentation covers shell, first visual, predictor readiness, and painted interaction", () => {
  for (const eventName of [
    "initial-page-shell",
    "first-useful-chart",
    "full-tab-readiness",
    "predictor-landscape-ready",
    "distribution-explorer-ready",
    "interaction-response",
  ]) {
    assert.match(step + landscape + distribution + secondary + performanceSource, new RegExp(eventName));
  }
  assert.match(performanceSource, /name\.endsWith\("-ready"\)/);
  assert.match(landscape + secondary, /painted-selection-response/);
});
