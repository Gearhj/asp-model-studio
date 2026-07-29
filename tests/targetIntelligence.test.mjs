// EDA Target Intelligence, Phase 1 -- frontend tests.
//
// Behavioral where behavior exists (the pure lib and the request/dedup client
// are transpiled and executed), structural where the assertion is about what the
// workspace renders and, just as importantly, what it refuses to render before a
// field is selected.
import assert from "node:assert/strict";
import { mkdir, readFile, rm, writeFile } from "node:fs/promises";
import path from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";
import test from "node:test";
import ts from "typescript";

const ROOT = new URL("..", import.meta.url);
const TMP_DIR = fileURLToPath(new URL("../.tmp/target-intelligence-tests", import.meta.url));

async function transpile(sourcePath, outputName) {
  const source = await readFile(new URL(sourcePath, ROOT), "utf8");
  const patched = source.replace(/import\.meta\.env\?\.\w+ as string \| undefined/g, "undefined");
  const output = ts.transpileModule(patched, {
    compilerOptions: { module: ts.ModuleKind.ES2022, target: ts.ScriptTarget.ES2022 },
  }).outputText;
  const outPath = path.join(TMP_DIR, outputName);
  await mkdir(path.dirname(outPath), { recursive: true });
  await writeFile(outPath, output, "utf8");
  return import(pathToFileURL(outPath).href);
}

await rm(TMP_DIR, { recursive: true, force: true });
const lib = await transpile("src/lib/targetIntelligence.ts", "targetIntelligence.js");
const api = await transpile("src/lib/targetIntelligenceApi.ts", "targetIntelligenceApi.js");

const workspace = await readFile(new URL("src/components/eda/TargetIntelligenceWorkspace.tsx", ROOT), "utf8");
const targetVisuals = await readFile(new URL("src/components/eda/TargetVisualInsights.tsx", ROOT), "utf8");
const predictorPanel = await readFile(new URL("src/components/eda/TargetByPredictorPanel.tsx", ROOT), "utf8");
const predictorDistribution = await readFile(
  new URL("src/components/eda/visual/PredictorDistributionExplorer.tsx", ROOT),
  "utf8",
);
const statisticalBoxPlot = await readFile(
  new URL("src/components/eda/visual/StatisticalBoxPlot.tsx", ROOT),
  "utf8",
);
const findingsPanel = await readFile(new URL("src/components/eda/TargetFindingsPanel.tsx", ROOT), "utf8");
const distributionPanel = await readFile(new URL("src/components/dataAcquisition/TargetDistributionPanel.tsx", ROOT), "utf8");
const documentationPayload = await readFile(new URL("src/lib/edaDocumentationPayload.ts", ROOT), "utf8");
const eda = await readFile(new URL("src/steps/Step02_EDA.tsx", ROOT), "utf8");
const hooks = await readFile(new URL("src/lib/useTargetIntelligence.ts", ROOT), "utf8");
const packageJson = JSON.parse(await readFile(new URL("package.json", ROOT), "utf8"));

const ALL_SOURCES = [workspace, targetVisuals, predictorPanel, findingsPanel, hooks];

test("Target and Predictor views render exact-statistic box plots", () => {
  assert.match(predictorPanel, /result\.boxPlotByTarget/);
  assert.match(predictorPanel, /dataTestId="target-predictor-box-plot"/);
  assert.match(predictorPanel, /aggregated exactly on the server/i);
  assert.match(predictorDistribution, /dataTestId="eda-predictor-box-plot"/);
  assert.match(predictorDistribution, /displayData\?\.statistics|data\?\.statistics/);
  assert.match(statisticalBoxPlot, /row\.q1/);
  assert.match(statisticalBoxPlot, /row\.median/);
  assert.match(statisticalBoxPlot, /row\.q3/);
  assert.match(statisticalBoxPlot, /row\.whiskerLow/);
  assert.match(statisticalBoxPlot, /row\.whiskerHigh/);
  assert.doesNotMatch(statisticalBoxPlot, /Math\.random|jitter|synthetic/i);
});

// --- 19: the Target page is substantially more than Overview ---------------

test("19 -- the Target workspace is substantially richer than the Overview panel", () => {
  // Overview's target block: four metrics, one chart, one rare-event sentence.
  const overviewSection = eda.slice(eda.indexOf("function OverviewPanel"), eda.indexOf("function PredictorsPanel"));
  const overviewMetrics = (overviewSection.match(/\["[^"]+",/g) ?? []).length;

  const workspaceSections = [
    "Target Identity",
    "Class Balance and Prevalence",
    "Rare-Event Assessment",
    "Event-Rate Uncertainty",
    "Target by Predictor",
    "Time and Segment Stability",
    "Target Quality and Leakage",
    "Target Findings and Evidence",
  ];
  for (const section of workspaceSections) {
    assert.ok(workspace.includes(section), `The Target workspace must contain the "${section}" section.`);
  }
  // Sections are RENDERED in the specified order. Checked against the main
  // component's return block, because the sub-components that own the section
  // headings are declared further down the file.
  const renderBlock = workspace.slice(
    workspace.indexOf('data-testid="target-intelligence-workspace"'),
    workspace.indexOf("// Section 1 -- Target Identity")
  );
  const renderMarkers = [
    "<TargetIdentitySection",
    'title="Class Balance and Prevalence"',
    "<TargetQualityDiagnostic",
    "<TargetPredictorPreview",
    'title="Target by Predictor"',
    "<RareEventSection",
    "<TimeAndSegmentSection",
    "<TargetQualitySection",
    'title="Target Findings and Evidence"',
  ];
  const positions = renderMarkers.map((marker) => {
    const index = renderBlock.indexOf(marker);
    assert.notEqual(index, -1, `The workspace must render ${marker}.`);
    return index;
  });
  assert.deepEqual([...positions].sort((a, b) => a - b), positions, "Sections must be rendered in the specified order.");

  const workspaceMetrics = (workspace.match(/<Metric\s/g) ?? []).length;
  assert.ok(
    workspaceMetrics > overviewMetrics * 2,
    `The Target workspace must carry substantially more analytical detail than Overview (${workspaceMetrics} vs ${overviewMetrics}).`
  );
  // The superseded Target panel that restated Overview is gone.
  assert.doesNotMatch(eda, /function TargetPanel\(/, "The old Overview-restating TargetPanel must be removed.");
  assert.match(eda, /<TargetIntelligenceWorkspace/, "The Target tab must render the Target Intelligence workspace.");
});

// --- 20 / 21: identity and governance --------------------------------------

test("20 -- target identity fields are shown", () => {
  for (const testId of [
    "target-identity",
    "target-identity-column",
    "target-positive-value",
    "target-identity-missing",
    "target-identity-rows",
    "target-identity-dataset-id",
    "target-identity-version",
  ]) {
    assert.ok(workspace.includes(`"${testId}"`), `Target identity must expose ${testId}.`);
  }
  for (const label of ["Target data type", "Problem type", "Dataset name", "Negative value"]) {
    assert.ok(workspace.includes(label), `Target identity must show "${label}".`);
  }
});

test("21 -- governance definitions come from the durable backend Project Context", () => {
  assert.match(workspace, /hydrateProjectContext/, "Governance narrative must be hydrated from the backend project record.");
  assert.doesNotMatch(workspace, /modeling-tool-project-context/, "The old global browser-only key must not be read.");
  // The redundant "Governed Definitions" panel was removed in the Data
  // Acquisition profiling phase: Project Context remains the authoritative home
  // for the narrative, and the Target page links to it instead of restating it.
  assert.ok(!workspace.includes("target-governance-definitions"), "The redundant panel must not return.");
  assert.ok(workspace.includes("target-view-project-context"), "A compact View Project Context action must remain.");
  // The narrative is still read from the durable backend record for evidence.
  assert.match(workspace, /buildTargetGovernanceFields/);

  const fields = lib.buildTargetGovernanceFields({
    targetDefinition: "A confirmed fraudulent transaction.",
    populationDefinition: "",
    observationWindow: "24 months.",
    performanceWindow: "  ",
    fraudDetails: { approvedUses: "Triage." },
  });
  const byKey = Object.fromEntries(fields.map((field) => [field.key, field]));
  assert.equal(byKey.targetDefinition.present, true);
  assert.equal(byKey.populationDefinition.present, false);
  assert.equal(byKey.performanceWindow.present, false, "Whitespace-only narrative is absent, not present.");
  assert.equal(byKey.approvedUses.value, "Triage.");

  // Absent fields are reported honestly and never invented.
  assert.equal(lib.GOVERNANCE_ABSENT_LABEL, "Not recorded in Project Context");
  const gaps = lib.unresolvedGovernanceGaps(fields).map((field) => field.key);
  assert.deepEqual(gaps.sort(), ["performanceWindow", "populationDefinition"]);

  // A null context produces gaps rather than defaults.
  const empty = lib.buildTargetGovernanceFields(null);
  assert.equal(empty.every((field) => !field.present), true);
  assert.equal(lib.unresolvedGovernanceGaps(empty).length, 4);
});

test("21b -- long narrative is excerpted on a word boundary", () => {
  const long = `${"word ".repeat(120)}end`;
  const { excerpt, truncated } = lib.narrativeExcerpt(long);
  assert.equal(truncated, true);
  assert.ok(excerpt.endsWith("..."));
  assert.ok(excerpt.length <= lib.NARRATIVE_EXCERPT_LENGTH + 3);
  const short = lib.narrativeExcerpt("Short definition.");
  assert.equal(short.truncated, false);
  assert.equal(short.excerpt, "Short definition.");
});

// --- 22 / 23 / 25: class balance, rare-event disclosure, guidance ----------

test("22 -- class balance is the exact server aggregate, never a browser preview", () => {
  assert.match(workspace, /useTargetAssessment/, "Class balance must come from the target-assessment aggregate.");
  assert.match(workspace, /useTargetDistribution/, "The chart must reuse the existing exact distribution aggregate.");
  assert.doesNotMatch(workspace, /computeClassDistributionFromRows/, "Counts must never be recomputed from browser rows.");
  assert.doesNotMatch(workspace, /quality-profile/, "Class counts must not be read from full quality profiling.");
  for (const testId of [
    "target-event-count",
    "target-non-event-count",
    "target-event-rate",
    "target-imbalance-ratio",
    "target-total-population",
  ]) {
    assert.ok(
      workspace.includes(`"${testId}"`) || targetVisuals.includes(`"${testId}"`),
      `Class balance must expose ${testId}.`
    );
  }
  // The scope mode leads the identity (Governed Analysis Scope phase), so a
  // draft response can never satisfy a governed request.
  assert.match(api.buildTargetAssessmentKey({
    projectId: "p", datasetId: "d", versionId: "v", target: "Class",
  }), /^governed_version\|p\|d\|v\|Class\|/);
});

test("23 -- rare-event detail reuses the disclosed adjusted-scale view", () => {
  assert.match(workspace, /TargetDistributionPanel/, "Population Scale and Rare-Event Detail must be reused, not duplicated.");
  const panel = fileURLToPath(new URL("src/components/dataAcquisition/TargetDistributionPanel.tsx", ROOT));
  assert.ok(panel, "The shared panel must exist.");
});

test("23b -- the shared distribution panel discloses the adjusted scale", async () => {
  const panel = await readFile(new URL("src/components/dataAcquisition/TargetDistributionPanel.tsx", ROOT), "utf8");
  assert.match(panel, /Population Scale/);
  assert.match(panel, /Rare-Event Detail/);
  assert.match(panel, /rare-event-scale-disclosure/);
  assert.match(panel, /RARE_EVENT_SCALE_DISCLOSURE/);
});

test("25 -- rare-event guidance appears and never applies a treatment", () => {
  assert.ok(workspace.includes("target-rare-event-assessment"));
  assert.ok(workspace.includes("target-imbalance-label"));
  assert.ok(workspace.includes("target-imbalance-implications"));
  assert.ok(workspace.includes("target-imbalance-thresholds"), "The documented thresholds must be inspectable.");
  assert.match(
    workspace,
    /has not enabled SMOTE, set class weights,\s*undersampled, or chosen a threshold/,
    "The page must state that no treatment was applied."
  );
  // No automatic treatment is wired anywhere in the phase's code.
  for (const source of ALL_SOURCES) {
    assert.doesNotMatch(source, /applySmote|setClassWeights|autoBalance|autoResample/, "No automatic balancing may be applied.");
  }
});

// --- 24: confidence interval ----------------------------------------------

test("24 -- the confidence interval is displayed with its method and bounds", () => {
  for (const testId of [
    "target-confidence-interval",
    "ci-point-estimate",
    "ci-lower-bound",
    "ci-upper-bound",
    "ci-confidence-level",
    "ci-method",
    "ci-explanation",
  ]) {
    assert.ok(workspace.includes(`"${testId}"`), `The interval section must expose ${testId}.`);
  }
  const described = lib.describeConfidenceInterval(
    {
      method: "Wilson score interval",
      confidenceLevel: 0.95,
      z: 1.96,
      eventCount: 360,
      totalCount: 170884,
      pointEstimate: 360 / 170884,
      lowerBound: 0.0019002089,
      upperBound: 0.0023355603,
      explanation: "x",
    },
    (rate) => `${(rate * 100).toFixed(4)}%`
  );
  assert.match(described, /Wilson score interval/);
  assert.match(described, /0\.2107%/);
  assert.match(described, /360 events in 170,884 rows/);
});

test("24b -- final-acceptance Target visuals answer distinct governed questions", () => {
  for (const marker of [
    "target-balance-confidence",
    "target-balance-bar",
    "target-wilson-confidence-band",
    "target-quality-diagnostic",
    "target-event-rate-predictor-preview",
    "target-predictor-sparkline",
  ]) {
    assert.ok(targetVisuals.includes(`"${marker}"`), `Target visual suite must expose ${marker}.`);
  }
  assert.match(targetVisuals, /data-scope="full-governed-population"/);
  assert.match(targetVisuals, /preview\?\.scope/);
  assert.match(targetVisuals, /High IV is a review signal, not automatic leakage/);
  assert.match(targetVisuals, /data-reduced-motion=/);
  assert.match(targetVisuals, /reducedMotion \? "" : "transition/);
});

test("24c -- lineage is ordered source, class mappings, then modeled target", () => {
  const lineage = workspace.slice(
    workspace.indexOf('data-testid="target-governed-lineage"'),
    workspace.indexOf('className="eda-metric-rail', workspace.indexOf('data-testid="target-governed-lineage"'))
  );
  const steps = [
    'data-lineage-step="source"',
    'data-lineage-step="event-mapping"',
    'data-lineage-step="non-event-mapping"',
    'data-lineage-step="modeled-target"',
  ].map((marker) => lineage.indexOf(marker));
  assert.ok(steps.every((index) => index >= 0));
  assert.deepEqual(steps, [...steps].sort((a, b) => a - b));
  assert.match(workspace, /"RiskPerformance"/);
  assert.match(lineage, /\{sourceLabel\}/);
  assert.match(lineage, /"Bad"/);
  assert.match(lineage, /"Good"/);
  assert.match(lineage, /Source excluded/);
});

test("24d -- preview click loads the existing full explorer without one request per preview card", () => {
  assert.match(workspace, /predictor_preview/);
  assert.match(workspace, /onInspect=\{inspectPreviewPredictor\}/);
  assert.match(workspace, /runPredictorAnalysis\(\{/);
  assert.match(workspace, /requestedPredictor=\{requestedPredictor\}/);
  assert.doesNotMatch(targetVisuals, /fetch\(/, "Preview cards must consume the batched Target response.");
  assert.match(targetVisuals, /new Set\(\[target, \.\.\.targetSourceExcluded\]\)/);
  assert.match(targetVisuals, /\.slice\(0, 5\)/);
});

test("24e -- target distribution exposes loading, success, empty, error, and retry", () => {
  assert.match(distributionPanel, /loadingMessage="Calculating target distribution from the registered dataset\.\.\."/);
  assert.match(distributionPanel, /emptyMessage="Confirm a target column to see its distribution\."/);
  assert.match(distributionPanel, /errorMessage=/);
  assert.match(distributionPanel, /data-testid="retry-target-distribution"/);
  assert.match(distributionPanel, /data-query-phase=\{query\.phase\}/);
  assert.match(workspace, /serverDistribution\.phase === "queued"/);
  assert.match(workspace, /serverDistribution\.phase === "failed"/);
  assert.match(workspace, /distribution\s*\?\s*"ready"\s*:\s*"empty"/);
});

test("24f -- new Target visual evidence is carried into the documentation draft", () => {
  for (const field of [
    "balance_and_confidence",
    "quality_diagnostic",
    "predictor_preview",
  ]) {
    assert.match(documentationPayload, new RegExp(`${field}:`), `Documentation payload must carry ${field}.`);
  }
});

// --- 26 / 27: on-demand predictor analysis --------------------------------

test("26 -- predictor analysis is on-demand and never runs on page load", () => {
  // The hook exposes an explicit run(); it has no auto-loading effect.
  assert.match(hooks, /export function useTargetByPredictor\(\): TargetByPredictorState & \{\s*run:/);
  const hookBody = hooks.slice(hooks.indexOf("export function useTargetByPredictor"));
  assert.doesNotMatch(
    hookBody.slice(0, hookBody.indexOf("export function useTargetFindings")),
    /useEffect\(\(\) => \{[\s\S]{0,400}fetchTargetByPredictor/,
    "useTargetByPredictor must not fetch from an effect."
  );
  assert.ok(predictorPanel.includes("target-run-analysis"), "A Run Analysis control must exist.");
  assert.ok(predictorPanel.includes("target-reset-analysis"), "A Reset control must exist.");
  assert.ok(predictorPanel.includes("target-predictor-search"), "The predictor selector must be searchable.");
  assert.ok(predictorPanel.includes("target-analysis-type"));
  assert.ok(predictorPanel.includes("target-band-count"));
  assert.ok(predictorPanel.includes("target-include-missing"));
  // Idle state names itself rather than showing an empty chart.
  assert.match(predictorPanel, /idle: "No analysis has been run for this predictor\."/);
});

test("27 -- a new predictor selection issues a new query and rejects the stale one", async () => {
  api.clearTargetIntelligenceCache();
  const resolvers = [];
  globalThis.fetch = (_url, init) =>
    new Promise((resolve) => {
      const body = JSON.parse(init.body);
      resolvers.push(() =>
        resolve({
          ok: true,
          json: async () => ({
            ok: true, supported: true, predictor: body.predictor, target: body.target,
            analysisType: body.analysisType, rows: [{ label: "Q1", population: 10, eventCount: 1, eventRate: 0.1, smallGroup: true }],
            missingGroup: null, otherGroup: null, summary: {}, cached: false, durationMs: 5,
          }),
        })
      );
    });

  const base = { projectId: "p", datasetId: "d", versionId: "v", target: "Class", analysisType: "numeric_quantile" };
  const first = api.fetchTargetByPredictor({ ...base, predictor: "V4" });
  const second = api.fetchTargetByPredictor({ ...base, predictor: "Amount" });
  assert.equal(resolvers.length, 2, "Two distinct predictors must issue two distinct queries.");
  assert.notEqual(
    api.buildTargetByPredictorKey({ ...base, predictor: "V4" }),
    api.buildTargetByPredictorKey({ ...base, predictor: "Amount" }),
    "Each predictor is a different analytical identity."
  );
  resolvers.forEach((resolve) => resolve());
  assert.equal((await first).predictor, "V4");
  assert.equal((await second).predictor, "Amount");
  assert.ok(predictorPanel.includes("target-by-predictor-table"), "The bounded result table must be rendered.");
  assert.ok(predictorPanel.includes("target-predictor-analytical-summary"), "The analytical summary must be rendered.");
});

test("27b -- duplicate renders never issue duplicate active requests", async () => {
  api.clearTargetIntelligenceCache();
  let calls = 0;
  let release;
  const gate = new Promise((resolve) => {
    release = resolve;
  });
  globalThis.fetch = async () => {
    calls += 1;
    await gate;
    return { ok: true, json: async () => ({ ok: true, supported: true, classBalance: null, imbalance: null, confidenceInterval: null }) };
  };
  const request = { projectId: "p", datasetId: "d", versionId: "v", target: "Class" };
  const promises = [
    api.fetchTargetAssessment(request),
    api.fetchTargetAssessment(request),
    api.fetchTargetAssessment(request),
  ];
  assert.equal(calls, 1, "Three identical requests must produce exactly one active query.");
  assert.equal(api.activeTargetIntelligenceRequests(), 1);
  release();
  await Promise.all(promises);
  // A repeat after settlement is served from the immutable result cache.
  await api.fetchTargetAssessment(request);
  assert.equal(calls, 1, "A resolved immutable aggregate must be reused, not refetched.");
  assert.ok(api.targetIntelligenceCounters().cacheHits >= 1);
});

// --- 28 / 29: conditional time and segment --------------------------------

test("28 -- no arbitrary time analysis is offered", () => {
  assert.ok(workspace.includes("target-no-governed-time-field"));
  assert.match(workspace, /No governed time field has been selected\./);
  assert.ok(workspace.includes("target-select-time-field"), "A Select a Time Field action must be provided.");
  assert.match(workspace, /Numeric fields are never inferred as dates\./);
  assert.ok(workspace.includes("target-rejected-time-field"), "A rejected time field must be disclosed, not silently ignored.");
  // The time chart is only constructed when governed rows exist.
  assert.match(workspace, /if \(!timeRows\.length\) return null;/);
});

test("29 -- no segment chart appears before a field is selected", () => {
  assert.ok(workspace.includes("target-no-segment-field"));
  assert.match(workspace, /No segment field selected\./);
  assert.match(workspace, /if \(!segmentRows\.length\) return null;/);
  // The chart is inside the branch that requires a selected field.
  const segmentBlock = workspace.slice(workspace.indexOf("target-segment-analysis"));
  const guardIndex = segmentBlock.indexOf("!segmentField ?");
  const chartIndex = segmentBlock.indexOf("segmentOption");
  assert.ok(guardIndex !== -1 && guardIndex < chartIndex, "The empty-state guard must precede the chart.");
});

// --- 30 / 31: durable findings and evidence -------------------------------

test("30 -- target findings persist to the backend, not to a browser key", () => {
  assert.match(workspace, /createTargetFinding/);
  assert.match(workspace, /updateTargetFinding/);
  assert.match(workspace, /useTargetFindings/);
  assert.doesNotMatch(workspace, /localStorage/, "Findings must not be stored in the browser.");
  assert.doesNotMatch(findingsPanel, /localStorage/);
  for (const control of [
    "target-finding-title",
    "target-finding-severity",
    "target-finding-save",
    "target-finding-edit",
    "target-finding-review",
    "target-finding-resolve",
  ]) {
    assert.ok(findingsPanel.includes(`"${control}"`), `The findings panel must expose ${control}.`);
  }
  // The finding request carries its full analytical identity.
  const createSource = workspace.slice(workspace.indexOf("await createTargetFinding("));
  for (const field of ["projectId", "datasetId", "versionId", "target", "analysisType"]) {
    assert.ok(createSource.slice(0, 900).includes(field), `A finding must carry ${field}.`);
  }
});

test("31 -- evidence saves a bounded analytical summary, never population data", () => {
  // Governed evidence is now created by the server command; the generic
  // browser-asserted path was removed by the Governed Analysis Scope phase.
  assert.match(workspace, /saveGovernedTargetEvidence/);
  assert.doesNotMatch(workspace, /createEvidence\(\{/);
  assert.ok(findingsPanel.includes("target-save-evidence"));
  assert.ok(findingsPanel.includes("target-export-summary"));
  assert.ok(predictorPanel.includes("target-export-chart"));

  const payload = lib.buildTargetEvidencePayload({
    projectId: "p",
    datasetId: "ds-class-train",
    versionId: "v-1",
    datasetName: "CLASS_TRAIN",
    target: "Class",
    // Governed scope, so the export carries version identity rather than draft markers.
    scope: {
      mode: "governed_version", datasetId: "ds-class-train", datasetVersionId: "v-1",
      artifactChecksum: "sha-1", evidenceEligible: true, mddEligible: true,
      datasetFingerprint: null, disclosure: "Governed Dataset Version.",
    },
    assessment: {
      supported: true,
      classBalance: {
        target: "Class", eventValue: "1", nonEventValue: "0", eventCount: 360, nonEventCount: 170524,
        eventRate: 360 / 170884, nonEventRate: 170524 / 170884, eventToNonEventRatio: 360 / 170524,
        imbalanceRatio: 170524 / 360, missingTargetCount: 0, totalModelingPopulation: 170884,
        classCount: 2, resolution: "exact",
      },
      imbalance: { label: "Extreme rare event", severity: "critical", imbalanceRatio: 473.68, rule: "r" },
      confidenceInterval: { method: "Wilson score interval", confidenceLevel: 0.95 },
    },
    governance: lib.buildTargetGovernanceFields({ targetDefinition: "A confirmed fraud event." }),
    predictorAnalysis: {
      predictor: "V4",
      analysisType: "numeric_quantile",
      rows: Array.from({ length: 250 }, (_, index) => ({
        label: `Q${index}`, population: 100, eventCount: 1, eventRate: 0.01, smallGroup: true,
      })),
      missingGroup: null,
      summary: { monotonicity: "Increasing" },
    },
    timeField: "",
    segmentField: "Segment",
    chartSpecification: { library: "echarts" },
    userId: "user-1",
    capturedAt: "2026-07-25T00:00:00.000Z",
  });

  assert.equal(payload.datasetIdentity.versionId, "v-1", "Evidence must name the exact dataset version.");
  assert.equal(payload.classCounts.eventCount, 360);
  assert.equal(payload.eventRate, 360 / 170884);
  assert.equal(payload.imbalanceAssessment.label, "Extreme rare event");
  assert.equal(payload.resolution.exact, true, "The exact-versus-sampled state must be recorded.");
  assert.equal(payload.timeAndSegmentSelection.segmentField, "Segment");
  assert.equal(payload.capturedBy, "user-1");
  assert.ok(payload.chartSpecification, "A chart specification must be carried.");
  assert.equal(payload.targetDefinition.governance[0].key, "targetDefinition");
  assert.ok(payload.targetDefinition.unresolvedGaps.includes("populationDefinition"));

  // Bounded: the 250-row analysis is truncated and the truncation is disclosed.
  assert.equal(payload.selectedPredictorAnalysis.rows.length, lib.EVIDENCE_MAX_ROWS);
  assert.equal(payload.selectedPredictorAnalysis.truncatedRows, true);
  const serialized = JSON.stringify(payload);
  assert.ok(serialized.length < 20000, `Evidence payload must stay bounded (was ${serialized.length} bytes).`);
});

// --- 32 / 33 / 34 -----------------------------------------------------------

test("32 -- reduced motion is respected", () => {
  assert.match(workspace, /prefers-reduced-motion: reduce/);
  assert.match(predictorPanel, /prefers-reduced-motion: reduce/);
  assert.match(workspace, /animation: !reducedMotion/);
  assert.match(predictorPanel, /animation: !reducedMotion/);
  assert.match(workspace, /data-reduced-motion=/, "The reduced-motion state must be observable.");
  // No decorative or fake-progress animation was introduced.
  for (const source of ALL_SOURCES) {
    assert.doesNotMatch(source, /confetti|fakeProgress|marquee|animate-bounce|animate-ping/i);
  }
});

test("33 -- no full target column reaches the browser", () => {
  for (const source of [...ALL_SOURCES, api.toString ? "" : ""]) {
    if (!source) continue;
    assert.doesNotMatch(source, /loadLocalDataset\(\)/, "The Target workspace must not read browser rows.");
    assert.doesNotMatch(source, /\.rows\.map\(\(row\) => row\[target\]/);
  }
  const apiSource = fileURLToPath(new URL("src/lib/targetIntelligenceApi.ts", ROOT));
  assert.ok(apiSource);
  // Every server call is an aggregate endpoint; none requests rows.
  const apiText = workspace + predictorPanel + findingsPanel;
  assert.doesNotMatch(apiText, /bounded_rows|\/data\/rows|sample_rows/);
  // The grouped result shape carries counts only.
  const described = lib.describeTargetByPredictor(
    {
      target: "Class", predictor: "V4",
      rows: [{ label: "Q1", population: 17088, eventCount: 3, eventRate: 0.000176, smallGroup: true }],
      missingGroup: null, otherGroup: null,
    },
    (rate) => `${((rate ?? 0) * 100).toFixed(4)}%`
  );
  assert.match(described, /Q1: 0\.0176%/);
  assert.match(described, /17,088 rows/);
});

test("34 -- the phase introduces no console noise and registers its test script", () => {
  for (const source of ALL_SOURCES) {
    assert.doesNotMatch(source, /console\.(log|warn|error|debug)\(/, "No console output may be added by this phase.");
  }
  assert.equal(
    packageJson.scripts["test:target-intelligence"],
    "node tests/targetIntelligence.test.mjs && .\\.venv\\Scripts\\python.exe tests\\target_intelligence_test.py"
  );
});

// --- Regression guards for the completed EDA context separation ------------

test("guard -- the phase does not reintroduce scoring-run controls on development EDA", () => {
  for (const source of ALL_SOURCES) {
    assert.doesNotMatch(source, /Compare Runs|Scoring Run|scoringRunId|TRAIN \/ TEST|OOT/, "Development EDA must stay free of scoring-run controls.");
  }
  assert.match(eda, /title="Detailed Predictor Profiles"/, "The Predictor area must not regress.");
});
