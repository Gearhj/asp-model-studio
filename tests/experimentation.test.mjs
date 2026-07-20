import fs from "node:fs";
import assert from "node:assert/strict";
import { mkdir, rm, writeFile } from "node:fs/promises";
import path from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";
import ts from "typescript";

const abLib = fs.readFileSync("src/lib/abTestingWorkflow.ts", "utf8");
const persistenceSource = fs.readFileSync("src/lib/abTestingWorkflowPersistence.ts", "utf8");
const workflows = fs.readFileSync("src/config/workflows.ts", "utf8");
const workflowPage = fs.readFileSync("src/steps/WorkflowPlaceholderStep.tsx", "utf8");
const stepShell = fs.readFileSync("src/components/StepShell.tsx", "utf8");
const overview = fs.readFileSync("src/steps/ProjectOverview.tsx", "utf8");
const copilotSource = fs.readFileSync("src/components/CopilotCard.tsx", "utf8");
const packageJson = JSON.parse(fs.readFileSync("package.json", "utf8"));
const abBackendService = fs.readFileSync("server/experimentation/ab_service.py", "utf8");
const abBackendRouter = fs.readFileSync("server/experimentation/ab_router.py", "utf8");
const ROOT = new URL("..", import.meta.url);
const TMP_DIR = fileURLToPath(new URL("../.tmp/experimentation-tests", import.meta.url));

class MemoryStorage {
  constructor() {
    this.map = new Map();
  }
  get length() {
    return this.map.size;
  }
  clear() {
    this.map.clear();
  }
  getItem(key) {
    return this.map.has(key) ? this.map.get(key) : null;
  }
  key(index) {
    return Array.from(this.map.keys())[index] ?? null;
  }
  removeItem(key) {
    this.map.delete(key);
  }
  setItem(key, value) {
    this.map.set(String(key), String(value));
  }
}

const browserEvents = [];
globalThis.localStorage = new MemoryStorage();
globalThis.CustomEvent = class CustomEvent {
  constructor(type, init = {}) {
    this.type = type;
    this.detail = init.detail;
  }
};
globalThis.window = {
  dispatchEvent(event) {
    browserEvents.push(event);
    return true;
  },
};

async function transpileSource(sourcePath, outputPath) {
  const source = fs.readFileSync(new URL(sourcePath, ROOT), "utf8");
  const output = ts.transpileModule(source, {
    compilerOptions: {
      module: ts.ModuleKind.ES2022,
      target: ts.ScriptTarget.ES2022,
    },
  }).outputText;
  await mkdir(path.dirname(outputPath), { recursive: true });
  await writeFile(outputPath, output, "utf8");
}

await rm(TMP_DIR, { recursive: true, force: true });
await transpileSource("src/config/workflows.ts", path.join(TMP_DIR, "src/config/workflows.js"));
await transpileSource("src/lib/datasetLibrary.ts", path.join(TMP_DIR, "src/lib/datasetLibrary"));
await transpileSource("src/lib/abTestingWorkflowPersistence.ts", path.join(TMP_DIR, "src/lib/abTestingWorkflowPersistence.js"));
await transpileSource("src/lib/abTestingWorkflow.ts", path.join(TMP_DIR, "src/lib/abTestingWorkflow.js"));
const workflowConfig = await import(pathToFileURL(path.join(TMP_DIR, "src/config/workflows.js")).href);
const abPersistence = await import(pathToFileURL(path.join(TMP_DIR, "src/lib/abTestingWorkflowPersistence.js")).href);
const abWorkflow = await import(pathToFileURL(path.join(TMP_DIR, "src/lib/abTestingWorkflow.js")).href);

assert.match(packageJson.scripts["test:experimentation"], /experimentation_backend_test\.py/);

for (const expected of [
  "data_full.csv",
  "Full dataset artifact is not loaded.",
  "validAnalysisRecords",
  "fullDatasetAvailable",
  "normalize_column_name",
  "daySegments",
  "hourSegments",
]) {
  assert.match(abBackendService, new RegExp(expected.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")), `Missing A/B backend artifact: ${expected}`);
}
assert.match(abBackendRouter, /\/experimentation\/ab\/analyze/);

for (const expected of [
  'dataset: "AB_MARKETING.csv"',
  'dataset: "AB_WORKFLOW.csv"',
  "AB_WORKFLOW_DEFAULTS",
  "AB_WORKFLOW_SAMPLE",
  "AB_WORKFLOW_FULL_ROW_COUNT",
  "AB_WORKFLOW_FULL_VALID_ANALYSIS_RECORDS",
  "profileAbDataset",
  "getAbWorkflowRows",
  "getAbWorkflowFullDatasetArtifact",
  "getAbPreviewAnalysisDataset",
  "normalizeAbColumnName",
  "compact_browser_cache",
  "full_dataset_artifact",
  "Preview only, not full experiment analysis",
  "Full dataset artifact is not loaded. Reopen or reload the confirmed dataset before running experiment analysis.",
  'unitIdColumn: "user.id"',
  'treatmentColumn: "test.group"',
  'treatmentValue: "ad"',
  'controlValue: "psa"',
  'outcomeColumn: "converted"',
  'successEvent: "True"',
  'exposureColumn: "total.ads"',
  '"most.ads.day"',
  '"most.ads.hour"',
  "isSuccessOutcome",
  "summarizeAbGroups",
  "allocationImbalance",
  "analyzeAbLift",
  "segmentLiftRows",
  "decisionRecommendationReason",
]) {
  assert.match(abLib, new RegExp(expected.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")), `Missing A/B library artifact: ${expected}`);
}

const fullArtifact = abWorkflow.getAbWorkflowFullDatasetArtifact(abWorkflow.AB_WORKFLOW_DEFAULTS);
assert.equal(fullArtifact.status.fullDatasetAvailable, true, "AB_WORKFLOW full artifact must be marked available when loaded.");
assert.equal(fullArtifact.status.source, "full_dataset_artifact");
assert.equal(fullArtifact.status.rowCount, 588101, "AB_WORKFLOW.csv full artifact should expose the expected 588K row count.");
assert.equal(fullArtifact.profile.rows, 588101, "Full dataset row count must flow into profile metrics.");
assert.equal(fullArtifact.summary.treatmentCount > 100000, true, "Segment and analysis summaries must not use the 14-row cached fallback.");
assert.equal(fullArtifact.summary.controlCount > 10000, true, "Control count must come from full dataset summary, not preview rows.");
assert.equal(fullArtifact.aggregates.outcomeSuccess, fullArtifact.summary.treatmentConversions + fullArtifact.summary.controlConversions, "Outcome distribution must use full-data conversion totals.");
assert.equal(fullArtifact.aggregates.outcomeSuccess + fullArtifact.aggregates.outcomeNonSuccess, 588101, "Full-data outcome distribution must reconcile to valid analysis records.");
assert.equal(fullArtifact.aggregates.exposureAvailable, false, "Reference artifacts without a governed exposure aggregate must not substitute preview-row exposure summaries.");
assert.equal(fullArtifact.daySegments.every((row) => row.treatmentCount + row.controlCount > 1000), true, "Segment counts must be calculated from the full dataset artifact.");
assert.equal(fullArtifact.daySegments.some((row) => row.treatmentCount === 2 || row.controlCount === 1), false, "Full segment counts must not show 14-row preview counts like 2/1.");

const previewArtifact = abWorkflow.getAbPreviewAnalysisDataset(abWorkflow.AB_WORKFLOW_DEFAULTS, "preview_rows");
assert.equal(previewArtifact.status.fullDatasetAvailable, false);
assert.equal(previewArtifact.status.previewOnly, true);
assert.equal(previewArtifact.status.message, "Preview only, not full experiment analysis");
assert.equal(previewArtifact.status.rowCount, 14, "Preview artifact remains small but must be explicitly labeled preview-only.");

const compactArtifact = abWorkflow.getAbPreviewAnalysisDataset(abWorkflow.AB_WORKFLOW_DEFAULTS, "compact_browser_cache");
assert.equal(compactArtifact.status.source, "compact_browser_cache");
assert.match(compactArtifact.status.message, /Full dataset artifact is not loaded/);
assert.equal(abWorkflow.normalizeAbColumnName("user id"), "user.id");
assert.equal(abWorkflow.normalizeAbColumnName("test group"), "test.group");
assert.equal(abWorkflow.normalizeAbColumnName("total ads"), "total.ads");

for (const expected of [
  "saveAbTestingStep",
  "loadAbTestingStep",
  "atlas-workflow-node-state",
  "atlas-ab-testing-workflow-step",
  "workflowType: \"ab_testing\"",
  "stepRoute?: string",
  "compactAbTestingStepPayload",
  "compactCalculatedMetrics",
  "safeSetLocalStorage",
  "pruneAbTestingWorkflowStorage",
  "clearAbTestingWorkflowStorage",
  "AB_TESTING_MAX_PAYLOAD_BYTES",
]) {
  assert.match(persistenceSource, new RegExp(expected.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")), `Missing A/B persistence artifact: ${expected}`);
}

for (const expected of [
  "Data Acquisition and Experiment Mapping",
  "Governed dataset source",
  "AB_WORKFLOW.csv",
  "Confirm Data Acquisition and Mapping",
  "Save Data Acquisition Evidence",
  "Upload experiment data",
  "Select from Dataset Library",
  "No experiment metrics are calculated until the full artifact and mappings validate.",
  "No calculated metrics shown yet.",
  "analyzeRegisteredAbDataset",
  "mappingValidatedAt",
  "dataSourceKind",
  "Unit ID column",
  "Treatment column",
  "Treatment value",
  "Control value",
  "Outcome column",
  "Exposure / intensity column optional",
  "Segment columns optional",
  "Date / time column optional",
  "Rows",
  "Unique units",
  "Duplicate units",
  "Missing unit ID",
  "Treatment values detected",
  "Treatment group count",
  "Control group count",
  "Allocation ratio",
  "Full dataset row count",
  "Valid analysis records",
  "registered full dataset artifact",
  "Full dataset artifact is not loaded.",
  "Full dataset artifact is not loaded. Reopen or reload the confirmed dataset before running experiment analysis.",
  "Compact browser cache",
  "Preview only, not full experiment analysis",
  "Preview rows and compact restored browser state are allowed for mapping and UI validation only.",
  "markAbFullDatasetArtifactLoaded",
  "getAbFullDatasetSession",
  "buildAbAnalysisDataset",
  "fullDatasetArtifactId",
  "fullDatasetRowCount",
  "analysisDataSource",
  "Experiment Setup Controls",
  "The source dataset does not include explicit experiment start or end dates.",
  "Population and Eligibility Checks",
  "This dataset is structurally clean for A/B testing review. Production decisioning uses the full confirmed dataset artifact only.",
  "Treatment / Control Design From Confirmed Data",
  "Observed allocation differs from the expected 1:1 design.",
  "Review Controls",
  "Expected allocation ratio",
  "Randomization / assignment method",
  "Balance variables selected for review",
  "Exposure variable interpretation",
  "Minimum acceptable group size",
  "Allocation imbalance acceptable?",
  "Exposure imbalance acceptable?",
  "Segment imbalance acceptable?",
  "Reviewer conclusion",
  "Proceed with caution",
  "Post-assignment exposure intensity",
  "Acceptable for workflow testing only",
  "Metrics Setup From Confirmed Dataset Columns",
  "Practical significance is the minimum lift that would matter for a business decision",
  "Segment analysis involves multiple comparisons.",
  "Power Assumptions",
  "Baseline conversion rate",
  "Minimum detectable relative lift",
  "Desired power",
  "One-sided vs two-sided test",
  "Current sample source",
  "Required treatment sample",
  "Required control sample",
  "Current treatment sample",
  "Current control sample",
  "Detectable relative lift at current sample",
  "Full dataset artifact",
  "Power and Sample Size",
  "Experiment EDA From Confirmed Dataset",
  "Experiment EDA Controls",
  "Chart grouping",
  "Treatment vs Control",
  "Minimum segment size warning threshold",
  "Outcome evidence uses",
  "Treatment / Control Allocation",
  "Outcome Distribution",
  "Conversion Rate by Group",
  "Exposure Distribution by Group",
  "Segment Size Review",
  "Segment Conversion Review",
  "Treatment share",
  "Control share",
  "Overall conversion rate",
  "Outcome missing count",
  "Missing mapped values",
  "Small sample warning",
  "Full dataset row count",
  "Segment cells below minimum size",
  "No date column available",
  "Browser display sample (not evidence)",
  "Experiment data quality summary",
  "Total rows",
  "Treatment/control allocation table",
  "Outcome distribution table",
  "Exposure summary table",
  "Segment size table",
  "Segment conversion table",
  "Missingness by column",
  "Duplicate unit review",
  "No duplicate user.id values detected",
  "Save EDA Evidence",
  "Export EDA Summary",
  "Open Chart Studio",
  "Open Analytics Workbench",
  "Formal Treatment-Effect Analysis",
  "Experiment Analysis Controls",
  "Two-proportion z-test",
  "Treatment greater than control",
  "Inference uses",
  "Treatment sample size",
  "Control sample size",
  "Statistical significance",
  "Practical significance",
  "Power status",
  "Decision readiness",
  "Conversion Rate Comparison",
  "Confidence Interval / Lift Plot",
  "Treatment / Control Counts",
  "Decision Readiness Summary",
  "Confidence interval crosses zero",
  "ATLAS Interpretation",
  "The result is based on the full confirmed dataset artifact, not preview rows.",
  "Save Experiment Analysis Evidence",
  "Export Analysis Summary",
  "atlas-ab-testing-analysis-summary.json",
  "Segment-Level Treatment Review",
  "Segment Analysis Controls",
  "Show only segments meeting sample threshold",
  "Sort by lift / p-value / sample size",
  "Lift descending",
  "segmentMinimumSizeTouched",
  "Segments reviewed",
  "shown /",
  "Segments below minimum size",
  "Largest positive lift segment",
  "Largest negative lift segment",
  "Segments statistically significant",
  "Segments practically significant",
  "Multiple-comparison method",
  "Segment recommendation",
  "Segment Lift Chart",
  "Segment Conversion Rate Chart",
  "Segment Sample Size Chart",
  "Significance / Reliability View",
  "Structured segment results table",
  "Adjusted p-value",
  "Sample-size flag",
  "Multiple comparisons warning",
  "Segment sample-size warning",
  "Production segment inference warning",
  "Segment results should be interpreted with multiple-comparison correction, segment sample size, and the overall experiment result.",
  "No segment rows available under the current threshold filter.",
  "No segments meet the current minimum sample-size threshold.",
  "The current threshold is",
  "If this is a preview-only view, reload the full dataset artifact before interpreting segment results.",
  "Show all exploratory segments",
  "Use demo threshold: 2",
  "Reset threshold to 30",
  "Exploratory only, no segment meets threshold",
  "ATLAS Segment Interpretation",
  "Save Segment Analysis Evidence",
  "Export Segment Summary",
  "atlas-ab-testing-segment-summary.json",
  "Business Impact Scenario Analysis",
  "Business Impact Assumptions",
  "Expected rollout population",
  "Revenue per conversion",
  "Cost per treatment exposure",
  "Expected treatment adoption / exposure rate",
  "Lift estimate to use",
  "Observed absolute lift",
  "Lower confidence bound",
  "Conservative adjusted lift",
  "Manual lift assumption",
  "Confidence scenario",
  "Optimistic",
  "Conservative",
  "Break-even",
  "Cost basis",
  "Per treatment exposure",
  "Business decision threshold",
  "Net impact > 0",
  "Conservative lift estimate",
  "Incremental conversions",
  "Incremental revenue",
  "Treatment cost",
  "Net impact",
  "ROI",
  "Break-even lift",
  "Business impact status",
  "Business impact warning",
  "Business impact scenario table",
  "Net Impact by Scenario",
  "Incremental Conversion Scenario",
  "Break-even Review",
  "Sensitivity Review",
  "Scenario value warning",
  "ATLAS Business Impact Interpretation",
  "The observed lift produces a positive business-impact scenario under the current assumptions",
  "Save Business Impact Evidence",
  "Export Business Impact Summary",
  "atlas-ab-testing-business-impact-summary.json",
  "Decision Cockpit",
  "Final Experiment Decision",
  "Decision: {finalDecision}",
  "Inconclusive, Run Longer",
  "Statistical evidence, practical significance, power at the selected MDE",
  "Launch readiness",
  "Not launch-ready",
  "powerAssessment.estimatedPower * 100",
  "Below practical threshold",
  "Allocation review required",
  "Directional Result",
  "outperformed {defaults.controlValue} in the confirmed sample.",
  "Treatment conversion rate: {treatmentRate}",
  "Control conversion rate: {controlRate}",
  "Observed lift: {observedLift}",
  "Statistical Conclusion",
  "Statistically significant.",
  "P-value: {pValue}",
  "Confidence interval {confidenceCrossesZero ? \"crosses zero\" : \"does not cross zero\"}.",
  "Business Conclusion",
  "Business scenario is positive under current assumptions, but the value estimate depends on uncertain lift.",
  "Required Next Action",
  "Resolve the configured launch blockers, then refresh the evidence and decision.",
  "Why ATLAS selected this decision",
  "If treatment lift is positive but statistical evidence, practical significance, or selected-MDE power is insufficient, recommend Inconclusive / Run Longer.",
  "Triggered rule: {launchBlockers.length ? launchBlockers.join(\" + \") : \"all configured launch thresholds passed\"} = {finalDecision}.",
  "What \"Run Longer\" Means",
  "Run longer means continue collecting treatment and control observations until the experiment has enough sample size",
  "Evidence Scorecard",
  "Decision Controls",
  "Decision recommendation",
  "Run longer",
  "Decision owner",
  "Decision date",
  "Launch readiness threshold",
  "Risk tolerance",
  "Follow-up action",
  "Collect more data",
  "Decision rationale",
  "Randomization quality",
  "Segment consistency",
  "Governance readiness",
  "Overall decision readiness",
  "Not launch-ready",
  "ATLAS Decision Recommendation",
  "Recommended decision: {finalDecision}.",
  "resolve ${launchBlockers.join",
  "Evidence supporting treatment",
  "Evidence weakening launch decision",
  "Required Next Actions Before Launch",
  "Retain confirmed full-dataset lineage and mapping evidence.",
  "Save evidence to Model Evidence Center.",
  "Attach final decision evidence to Model Documentation Studio.",
  "Decision recommendation table",
  "Launch treatment",
  "Keep control",
  "Segmented rollout",
  "Inconclusive",
  "Do not launch",
  "Final decision: ${finalDecision}.",
  "re-run power, treatment-effect, segment, business-impact, and governance review",
  "Save Decision Recommendation Evidence",
  "Export Decision Summary",
  "atlas-ab-testing-decision-summary.json",
  "Open Decision Journal",
  "A/B Testing Documentation Readiness",
  "Workflow steps completed",
  "Evidence sections mapped",
  "Evidence sections needing review",
  "Decision status",
  "MEC package status",
  "MDS attachment status",
  "Documentation Review Controls",
  "Documentation readiness decision",
  "Needs more evidence",
  "Attach evidence to Model Documentation Studio?",
  "Include limitations?",
  "Include monitoring plan?",
  "Documentation Coverage Matrix",
  "Workflow evidence source",
  "Evidence status",
  "MEC evidence type",
  "MDS section",
  "Reviewer action",
  "Experiment Evidence Package Preview",
  "Generated evidence list",
  "Project context evidence",
  "Decision recommendation evidence",
  "Required Documentation Gaps Before Final Approval",
  "Confirm the registered dataset version and full-artifact lineage.",
  "Complete post-decision plan.",
  "ATLAS Documentation Interpretation",
  "Save Documentation Review Evidence",
  "Attach Evidence to MDS",
  "Export A/B Testing Evidence Pack",
  "Post-Decision Plan",
  "Post-Decision Strategy",
  "Run longer / collect more data",
  "Launch treatment",
  "Keep control",
  "Slow rollout",
  "Segmented rollout",
  "Continue holdout test",
  "Do not launch",
  "Changing this selector updates the page sections",
  "Post-Decision Plan Summary",
  "Run longer / collect more data",
  "Current decision",
  "Post-decision strategy",
  "Launch status",
  "Do not launch yet",
  "Re-analysis required",
  "Run-Longer Action Plan",
  "Launch Treatment Plan",
  "Slow Rollout Checkpoint Plan",
  "Segmented Rollout Plan",
  "Holdout Continuation Plan",
  "Keep-Control Plan",
  "Do-Not-Launch Closure Plan",
  "Follow-up owner",
  "Target additional observations",
  "Minimum treatment sample target",
  "Minimum control sample target",
  "Re-analysis trigger",
  "Next review date",
  "Data refresh cadence",
  "Decision review owner",
  "Rollout owner",
  "Launch date",
  "Success metrics",
  "Guardrail metrics",
  "Rollback criteria",
  "Rollout checkpoints",
  "5%, 10%, 25%, 50%, 100%",
  "Approved segments",
  "Excluded segments",
  "Segment-level monitoring",
  "Stop/go criteria",
  "Post-Decision Metrics to Monitor",
  "Treatment sample size",
  "Control sample size",
  "Estimated power at selected MDE",
  "Business impact scenario",
  "Decision Re-entry Criteria",
  "Strategy-specific trigger",
  "Decision recommendation re-reviewed.",
  "Launch Guardrails if Decision Changes",
  "Do not launch unless treatment effect is statistically and practically meaningful.",
  "ATLAS Post-Decision Interpretation",
  "Because the final decision is ${finalDecision}",
  "Save Post-Decision Plan Evidence",
  "Attach Post-Decision Plan to MDS",
  "Export Post-Decision Plan",
  "atlas-ab-testing-post-decision-plan.json",
  "Finish A/B Testing Workflow",
  "Documentation Notes",
  "Allocation imbalance warning",
  "Exposure balance",
  "Control conversion rate",
  "Treatment conversion rate",
  "Absolute lift",
  "Relative lift",
  "Standard error",
  "Confidence interval",
  "P-value",
  "Segment column selector",
  "Bonferroni correction",
  "Benjamini-Hochberg FDR",
  "It does not rely only on p-value",
  "Save Evidence",
  "Open Model Evidence Center",
  "Attach to Model Documentation Studio",
  "Export Experiment Evidence Pack",
  "Documentation Review",
  "Post-Decision Plan",
  "onComplete();",
  "return false;",
  "saveAbTestingStep(",
  "stateRef.current",
  "handleAbTestingMarkCompleteAndNext",
  "ab-testing-mark-complete-next",
  "Developer Debug",
  "ab-testing-developer-debug",
  "This should not be required during normal workflow use",
  "Payload size:",
  "Saved compact A/B Testing step",
  "reclaimWorkflowStorage();",
  "may not persist locally because",
  "None for current step.",
  "Last action:",
  "Navigating to ${nextRoute}",
  "A/B Testing workflow step saved.",
  "A/B Testing workflow step could not be saved.",
  "Complete Data Acquisition before treating any suggested mapping as project evidence.",
  "Next step preview",
  "Next step: Data Acquisition and Experiment Mapping",
  "After you define the business context, ATLAS will ask you to select the experiment dataset and map the unit ID, treatment, control, outcome, exposure, segment, and date/time fields.",
  "Continue to Data Acquisition",
  "Risk level and intended use",
  "Decision to be made",
  "AbProjectContextNextStepPreview",
  "AbSelectionGuide",
  "How to choose field mappings",
  "How to choose EDA settings",
  "How to choose segment settings",
  "How to choose business assumptions",
  "How to choose a decision recommendation",
  "How to choose documentation readiness",
  "How to choose a post-decision strategy",
  "Best used for the independently assigned experimental unit.",
  "Full dataset artifact is not loaded. Reopen or reload the confirmed dataset before completing this analysis step.",
  "Selection Guide",
  "Choose the experiment type based on what decision the test supports.",
  "Marketing A/B test compares marketing messages, ads, offers, emails, pages, or campaign treatments",
  "Product / UX experiment",
  "Pricing experiment",
  "Policy experiment",
  "Content experiment",
  "Operational experiment",
  "Choose the design that best matches how treatment assignment was created.",
  "User-level randomized A/B test",
  "User-level randomized holdout",
  "Cluster randomized test",
  "Geo or market test",
  "Before/after test",
  "Quasi-experimental test",
  "Observational comparison",
  "Assignment unit is the entity assigned to treatment.",
  "Randomization unit is the entity randomized.",
  "Analysis unit is used in metric calculation.",
  "If users are assigned to ad or PSA, use user.id for all three.",
  "Choose the column that uniquely identifies the experimental unit",
  "Choose the column that identifies treatment assignment.",
  "Choose the column that records the success event or metric outcome.",
  "Exposure or intensity columns describe how much treatment the user received",
  "Segment columns help test whether treatment effects differ across subgroups",
  "Randomization Check determines whether treatment and control groups look reasonably comparable",
  "Use 1:1 for balanced experiments.",
  "Choose User-level randomized only if treatment was actually randomized at the user level.",
  "Do not use post-assignment exposure as proof of baseline balance.",
  "Proceed only means the analysis can continue.",
  "The primary metric is the main outcome used for the decision.",
  "Practical significance is the smallest lift that matters for the business.",
  "Use a multiple-comparison policy when reviewing many segments or secondary metrics.",
  "Usually the control conversion rate.",
  "The smallest proportional improvement over the control rate that the experiment should detect.",
  "Power is the chance of detecting a real effect if it exists.",
  "Use two-sided unless the decision was explicitly designed",
  "A positive observed lift does not prove the treatment works.",
  "Plain-English result",
  "Directionally favorable",
  "Practically meaningful",
  "Underpowered / Not launch-ready",
  "Segment analysis is exploratory unless segment hypotheses were pre-specified",
  "Minimum segment size protects against over-interpreting tiny segments.",
  "Business impact translates lift into dollars or value.",
  "Observed lift is optimistic when the experiment is underpowered.",
  "Use the number of users expected to receive the treatment after launch or rollout.",
  "Decision Recommendation combines statistical evidence, practical lift, power, randomization quality, segment reliability, business impact, and governance readiness.",
  "The recommendation should not rely on p-value alone.",
  "Run longer means continue collecting experiment observations until the sample is large enough",
  "This page defines what happens after the experiment decision.",
  "Focus on sample-size targets, data collection, re-analysis trigger, and next review date.",
  "Focus on rollout monitoring, guardrail metrics, rollback criteria, and post-launch review.",
  "Define phased rollout checkpoints such as 5%, 10%, 25%, 50%, and 100%",
  "Save Evidence Draft",
  "Evidence Readiness",
  "View Full Evidence Checklist",
  "Reviewer Notes",
  "AbEvidenceReadiness",
  "AbReviewerNotes",
  'step.label === "Data Acquisition and Experiment Mapping" && <AbDatasetMapping',
  "AbUnavailableSection",
  "dataReady={dataAcquisitionConfirmed}",
  "normalizeWorkflowOrder(\"ab-testing\");",
  "These are business assumptions.",
]) {
  assert.match(workflowPage, new RegExp(expected.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")), `Missing A/B workflow UI artifact: ${expected}`);
}

for (const forbidden of [
  "A/B Testing Save Debug",
  "Emergency: Clear A/B Testing cached workflow state",
  "<InfoGrid title=\"MEC Evidence Types\"",
  "AbCompactDataMapping",
  "Data Mapping Status",
  "Suggested defaults only",
  "AB_WORKFLOW.csv has only 8 treatment records and 6 control records.",
  "AB_WORKFLOW.csv contains only 14 records.",
  "14 unique user IDs",
  "Workflow test mode: minimum segment size has been set to 2 because AB_WORKFLOW.csv contains only 14 records.",
  "Segment results are exploratory only. AB_WORKFLOW.csv is too small for production segment inference.",
  "Continue to Experiment Setup",
  'segmentImbalanceAcceptable: "Needs caution due to small sample"',
  'powerAllocationRatio: "Observed 1.33:1"',
  '"2026-07-12"',
  '"16,928"',
  '"12,696"',
  '["Treatment sample size", "8"',
  '["Control sample size", "6"',
  "Statistical proof and power are insufficient",
]) {
  assert.doesNotMatch(workflowPage, new RegExp(forbidden.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")), `A/B workflow should not expose old debug or full evidence table: ${forbidden}`);
}

for (const expected of [
  "AbTestingGuideContext",
  "Documentation readiness",
  "Needs final review",
  "Post-decision planning",
  "Post-decision strategy",
  "No full launch approved",
  "Re-analysis required",
  "Task\" value=\"A/B Testing",
  "readWorkflowNodeState(projectId, \"ab-testing-2\")",
  "mappingConfirmed",
  "Dataset\" value={mapping?.dataset || \"Not confirmed\"}",
  "Unit ID\" value={mapping?.unitIdColumn || \"Not mapped\"}",
  "Treatment\" value={mapping?.treatmentValue || \"Not mapped\"}",
  "Control\" value={mapping?.controlValue || \"Not mapped\"}",
  "Outcome\" value={mapping?.outcomeColumn || \"Not mapped\"}",
  "Define after mapping",
  "decisionRecommendation",
  "postDecisionStrategy",
]) {
  assert.match(copilotSource, new RegExp(expected.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")), `Missing A/B Atlas Guide artifact: ${expected}`);
}

for (const expected of [
  "onNextClick?: React.MouseEventHandler<HTMLButtonElement>",
  "nextButtonTestId?: string",
  "nextStatusLine?: React.ReactNode",
  "nextDebugPanel?: React.ReactNode",
  'type="button"',
  "data-testid={nextButtonTestId}",
  "onClick={onNextClick ?? handleNext}",
]) {
  assert.match(stepShell, new RegExp(expected.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")), `Missing visible StepShell button artifact: ${expected}`);
}

for (const expected of [
  "Experiment Name",
  "Treatment Sample Size",
  "Control Sample Size",
  "Treatment Conversion Rate",
  "Control Conversion Rate",
  "Absolute Lift",
  "Relative Lift",
  "Decision recommendation",
]) {
  assert.match(overview, new RegExp(expected.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")), `Missing A/B overview artifact: ${expected}`);
}

const workflowRoutes = workflowConfig.getWorkflowDefinition("ab-testing").steps.map((step) => step.route);
const workflowLabels = workflowConfig.getWorkflowDefinition("ab-testing").steps.map((step) => step.label);
assert.deepEqual(workflowRoutes.slice(0, 15), [
  "/workflow/ab-testing/1",
  "/workflow/ab-testing/2",
  "/workflow/ab-testing/3",
  "/workflow/ab-testing/4",
  "/workflow/ab-testing/5",
  "/workflow/ab-testing/6",
  "/workflow/ab-testing/7",
  "/workflow/ab-testing/8",
  "/workflow/ab-testing/9",
  "/workflow/ab-testing/10",
  "/workflow/ab-testing/11",
  "/workflow/ab-testing/12",
  "/workflow/ab-testing/13",
  "/workflow/ab-testing/14",
  "/workflow/ab-testing/15",
]);
assert.deepEqual(workflowLabels.slice(0, 15), [
  "Project Context",
  "Data Acquisition and Experiment Mapping",
  "Experiment Setup",
  "Population and Eligibility",
  "Treatment / Control Design",
  "Randomization Check",
  "Metrics Setup",
  "Power and Sample Size",
  "Experiment EDA",
  "Experiment Analysis",
  "Segment Analysis",
  "Business Impact",
  "Decision Recommendation",
  "Documentation Review",
  "Post-Decision Plan",
]);

const persistenceCases = [
  ["ab-testing-1", "objective", "SAVE_TEST_PROJECT_CONTEXT_123", "/workflow/ab-testing/2"],
  ["ab-testing-2", "objective", "SAVE_TEST_DATA_ACQUISITION_123", "/workflow/ab-testing/3"],
  ["ab-testing-3", "objective", "SAVE_TEST_EXPERIMENT_SETUP_123", "/workflow/ab-testing/4"],
  ["ab-testing-4", "objective", "SAVE_TEST_POPULATION_ELIGIBILITY_123", "/workflow/ab-testing/5"],
];

for (const [stepId, field, value, nextRoute] of persistenceCases) {
  localStorage.setItem(`atlas-ab-testing-workflow-step:ab-persistence-test:${stepId}`, JSON.stringify({ datasetRows: Array.from({ length: 1000 }, () => ({ stale: true })) }));
  localStorage.setItem(`atlas-workflow-node-state:ab-persistence-test:${stepId}`, JSON.stringify({ previewRows: Array.from({ length: 1000 }, () => ({ stale: true })) }));
  const formValues = {
    objective: "",
    inputs: "",
    assumptions: "",
    validation: "",
    risks: "",
    decision: "",
    rationale: "",
    notes: "",
    numeric: {},
    [field]: value,
  };
  const result = abPersistence.saveAbTestingStep({
    projectId: "ab-persistence-test",
    workflowType: "ab_testing",
    stepId,
    stepSlug: stepId,
    stepNumber: Number(stepId.replace("ab-testing-", "")),
    stepRoute: `/workflow/ab-testing/${stepId.replace("ab-testing-", "")}`,
    formValues: {
      ...formValues,
      analysisSnapshot: { huge: "x".repeat(150000) },
      simulationResults: { powerByIteration: Array.from({ length: 1000 }, (_, index) => ({ index })) },
      previewRows: Array.from({ length: 100 }, () => ({ shouldNotPersist: true })),
    },
    calculatedMetrics: {
      nextRoute,
      datasetRows: Array.from({ length: 100 }, () => ({ shouldNotPersist: true })),
      previewRows: [{ shouldNotPersist: true }],
      variableSummaryTable: [{ shouldNotPersist: true }],
      downstreamSections: [{ shouldNotPersist: true }],
      route: `/workflow/ab-testing/${stepId.replace("ab-testing-", "")}`,
    },
    reviewerNotes: "reviewer note",
    evidenceStatus: "saved",
    completed: true,
    updatedAt: "2026-07-11T00:00:00.000Z",
  });
  const reloaded = abPersistence.loadAbTestingStep("ab-persistence-test", stepId);
  assert.equal(reloaded[field], value, `${stepId} must restore typed text after remount or reload.`);
  assert.equal(JSON.parse(localStorage.getItem(result.workflowNodeStorageKey))[field], value, `${stepId} must save typed text to workflow-node storage.`);
  const auditPayload = JSON.parse(localStorage.getItem(result.auditStorageKey));
  assert.equal(auditPayload.formValues[field], value, `${stepId} must save typed text to the A/B audit key.`);
  assert.equal(auditPayload.completed, true);
  assert.equal(auditPayload.workflowType, "ab_testing");
  assert.equal(auditPayload.stepNumber, Number(stepId.replace("ab-testing-", "")));
  assert.equal(auditPayload.formValues.analysisSnapshot, undefined, `${stepId} must not save analysis snapshots.`);
  assert.equal(auditPayload.formValues.simulationResults, undefined, `${stepId} must not save simulation results.`);
  assert.equal(auditPayload.formValues.previewRows, undefined, `${stepId} must not save preview rows.`);
  assert.equal(auditPayload.calculatedMetrics.datasetRows, undefined, `${stepId} must not save dataset rows.`);
  assert.equal(auditPayload.calculatedMetrics.previewRows, undefined, `${stepId} must not save preview rows.`);
  assert.equal(auditPayload.calculatedMetrics.variableSummaryTable, undefined, `${stepId} must not save variable summaries.`);
  assert.equal(auditPayload.calculatedMetrics.downstreamSections, undefined, `${stepId} must not save downstream sections.`);
  assert.equal(result.payloadBytes < abPersistence.AB_TESTING_MAX_PAYLOAD_BYTES, true, `${stepId} payload must be under 100 KB.`);
  assert.equal(result.browserCacheWritten, true, `${stepId} compact browser cache should write successfully.`);
  assert.equal(result.prunedKeys.some((key) => key.endsWith(`:${stepId}`)), true, `${stepId} must automatically prune stale current-step A/B cache before saving.`);
  assert.equal(result.retriedAfterQuota, false);
}

const mappingPersistenceResult = abPersistence.saveAbTestingStep({
  projectId: "ab-mapping-persistence-test",
  workflowType: "ab_testing",
  stepId: "ab-testing-2",
  stepSlug: "ab-testing-2",
  stepNumber: 2,
  formValues: {
    objective: "Confirmed full-data mapping",
    ab: {
      confirmed: true,
      dataset: "AB_WORKFLOW.csv",
      unitIdColumn: "user.id",
      treatmentColumn: "test.group",
      treatmentValue: "ad",
      controlValue: "psa",
      outcomeColumn: "converted",
      datasetColumns: ["user.id", "test.group", "converted", "total.ads", "most.ads.day", "most.ads.hour"],
      fullDatasetRowCount: 588101,
      analysisDataSource: "full_dataset_artifact",
      cachedDatasetProfile: { shouldNotPersist: true },
    },
  },
  completed: true,
});
const restoredMapping = abPersistence.loadAbTestingStep("ab-mapping-persistence-test", "ab-testing-2");
assert.equal(restoredMapping.ab.confirmed, true, "Confirmed A/B mapping must survive navigation and reload.");
assert.equal(restoredMapping.ab.dataset, "AB_WORKFLOW.csv");
assert.equal(restoredMapping.ab.unitIdColumn, "user.id");
assert.equal(restoredMapping.ab.fullDatasetRowCount, 588101);
assert.deepEqual(restoredMapping.ab.datasetColumns, ["user.id", "test.group", "converted", "total.ads", "most.ads.day", "most.ads.hour"]);
assert.equal(restoredMapping.ab.cachedDatasetProfile, undefined, "Derived A/B artifacts must not enter compact browser persistence.");
assert.equal(mappingPersistenceResult.payloadBytes < abPersistence.AB_TESTING_MAX_PAYLOAD_BYTES, true);

class QuotaOnceStorage extends MemoryStorage {
  constructor() {
    super();
    this.remainingFailures = 1;
  }
  setItem(key, value) {
    if (this.remainingFailures > 0) {
      this.remainingFailures -= 1;
      const error = new Error("quota forced once");
      error.name = "QuotaExceededError";
      throw error;
    }
    super.setItem(key, value);
  }
}

const quotaOnceStorage = new QuotaOnceStorage();
quotaOnceStorage.remainingFailures = 0;
quotaOnceStorage.setItem("atlas-ab-testing-workflow-step:ab-persistence-test:ab-testing-stale", "x".repeat(120000));
quotaOnceStorage.remainingFailures = 1;
const quotaRetryResult = abPersistence.saveAbTestingStep({
  projectId: "ab-persistence-test",
  workflowType: "ab_testing",
  stepId: "ab-testing-1",
  stepSlug: "ab-testing-1",
  stepNumber: 1,
  formValues: { objective: "SAVE_TEST_PROJECT_CONTEXT_123" },
  completed: true,
}, quotaOnceStorage);
assert.equal(quotaRetryResult.browserCacheWritten, true, "A/B save must retry after quota and succeed when pruning frees space.");
assert.equal(quotaRetryResult.retriedAfterQuota, true, "A/B save must report quota retry.");
assert.equal(quotaRetryResult.prunedKeys.some((key) => key.includes("ab-testing-stale")), true, "Quota retry must aggressively prune stale A/B keys.");
assert.equal(JSON.parse(quotaOnceStorage.getItem(quotaRetryResult.workflowNodeStorageKey)).objective, "SAVE_TEST_PROJECT_CONTEXT_123");

const failingStorage = {
  length: 0,
  getItem() {
    return null;
  },
  key() {
    return null;
  },
  removeItem() {},
  setItem() {
    const error = new Error("quota forced");
    error.name = "QuotaExceededError";
    throw error;
  },
};
const quotaResult = abPersistence.saveAbTestingStep({
  projectId: "ab-persistence-test",
  workflowType: "ab_testing",
  stepId: "ab-testing-1",
  stepSlug: "ab-testing-1",
  stepNumber: 1,
  formValues: { objective: "SAVE_TEST_PROJECT_CONTEXT_123" },
  completed: true,
}, failingStorage);
assert.equal(quotaResult.browserCacheWritten, false);
assert.equal(quotaResult.retriedAfterQuota, true);
assert.match(quotaResult.browserCacheError, /quota forced|Local storage quota exceeded/);

const oversizedInputResult = abPersistence.saveAbTestingStep({
  projectId: "ab-persistence-test",
  workflowType: "ab_testing",
  stepId: "ab-testing-1",
  stepSlug: "ab-testing-1",
  stepNumber: 1,
  formValues: { objective: "x".repeat(150000) },
  completed: true,
});
assert.equal(oversizedInputResult.payloadBytes < abPersistence.AB_TESTING_MAX_PAYLOAD_BYTES, true, "Oversized text input must be compacted under the payload limit before storage.");

localStorage.setItem("atlas-ab-testing-workflow-step:ab-persistence-test:ab-testing-old", "x".repeat(120000));
localStorage.setItem("atlas-workflow-node-state:ab-persistence-test:ab-testing-old", JSON.stringify({ objective: "old" }));
localStorage.setItem("atlas-workflow-node-state:ab-persistence-test:predictive-step", JSON.stringify({ objective: "keep" }));
const removedKeys = abPersistence.clearAbTestingWorkflowStorage("ab-persistence-test");
assert.equal(removedKeys.some((key) => key.includes("ab-testing-old")), true);
assert.equal(localStorage.getItem("atlas-workflow-node-state:ab-persistence-test:predictive-step") !== null, true, "Clear cache must not remove unrelated workflow state.");

const throwingStorage = {
  getItem() {
    return null;
  },
  length: 0,
  key() {
    return null;
  },
  removeItem() {},
  setItem() {
    throw new Error("forced save failure");
  },
};
const throwingResult = abPersistence.saveAbTestingStep({
  projectId: "ab-persistence-test",
  workflowType: "ab_testing",
  stepId: "ab-testing-1",
  stepSlug: "ab-testing-1",
  formValues: { objective: "SAVE_TEST_PROJECT_CONTEXT_123" },
  completed: true,
}, throwingStorage);
assert.equal(throwingResult.browserCacheWritten, false);
assert.match(throwingResult.browserCacheError, /forced save failure/);

console.log("experimentation workflow checks passed");
