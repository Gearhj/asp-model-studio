// UX-DATAACQ-001..004 + Part H: structural contract for the Data Acquisition page.
// Complements tests/dataAcquisitionLifecycle.test.mjs (which tests the decision
// logic behaviorally) by pinning the rendered structure those decisions drive.
import fs from "node:fs";
import assert from "node:assert/strict";

const page = fs.readFileSync("src/steps/Step01_DataAcquisition.tsx", "utf8");
const progressPanel = fs.readFileSync("src/components/dataAcquisition/DatasetLoadProgressPanel.tsx", "utf8");
const distributionPanel = fs.readFileSync("src/components/dataAcquisition/TargetDistributionPanel.tsx", "utf8");
const packageJson = JSON.parse(fs.readFileSync("package.json", "utf8"));

function sourceSection(source, startMarker, endMarker, label) {
  const start = source.indexOf(startMarker);
  const end = source.indexOf(endMarker, start + startMarker.length);
  assert.notEqual(start, -1, `Missing ${label} start marker.`);
  assert.ok(end > start, `Missing ${label} end marker.`);
  return source.slice(start, end);
}

assert.equal(packageJson.scripts["test:data-acquisition-lifecycle"], "node tests/dataAcquisitionLifecycle.test.mjs");
assert.equal(packageJson.scripts["test:data-acquisition-ux"], "node tests/dataAcquisitionUx.test.mjs");

// --- Part A: Load Selected Version -----------------------------------------

assert.match(page, /data-testid="dataset-load-command"/, "The dataset/version selectors and load action must live in one primary command area.");
assert.match(page, /data-testid="load-selected-version"/, "The load action must be addressable.");
assert.match(
  page,
  /data-load-state=\{isLoading \? "loading" : showLoaded \? "loaded" : failed \? "failed" : "unloaded"\}/,
  "The load action must expose its lifecycle state."
);
assert.match(page, /"Loading Selected Version\.\.\."/, "Loading label required.");
assert.match(page, /"Version Loaded"/, "Success label required.");
assert.match(page, /"Load Selected Version"/, "Unloaded label required.");
assert.match(page, /bg-blue-700 text-white/, "The unloaded action must be a blue primary button.");
assert.match(page, /bg-emerald-600 text-white/, "The loaded action must use a green success treatment.");
assert.match(page, /<Check size=\{16\}/, "The success state should carry a check icon.");
assert.match(page, /disabled=\{!canLoad\}/, "Loading must disable duplicate submission.");
assert.match(page, /aria-busy=\{isLoading\}/, "Loading must be announced assistively.");

// The action is inside its own command block, not stranded at the end of a
// selector row -- the old three-column `_auto` grid put it at the far right.
assert.doesNotMatch(page, /lg:grid-cols-\[minmax\(0,1fr\)_minmax\(240px,360px\)_auto\]/, "Load action must not sit at the far-right edge of the selector row.");

// Part A/5: changing either selector resets the loaded state.
const datasetChangeHandler = sourceSection(
  page,
  "onDatasetChange={",
  "onVersionChange={",
  "dataset-change handler",
);
const versionChangeHandler = sourceSection(
  page,
  "onVersionChange={",
  "onRefresh={",
  "version-change handler",
);
assert.match(datasetChangeHandler, /setLoadProgress\(IDLE_LOAD_PROGRESS\)/, "Changing dataset must reset load progress.");
assert.match(versionChangeHandler, /setLoadProgress\(IDLE_LOAD_PROGRESS\)/, "Changing version must reset load progress.");
assert.match(page, /isAlreadyLinked\(loadedLibraryIdentity, \{ datasetId: selectedLibraryDatasetId, versionId: selectedLibraryVersionId \}\)/, "Loaded state must be keyed to the exact loaded datasetId/versionId.");
assert.match(page, /const showLoaded = isLoaded && loadProgress\.phase === "loaded"/, "A success state must not survive a changed selection.");

// Part A/6-8: identity-based loaded message, never filename-as-identity.
assert.match(page, /Loaded \$\{dataset\?\.name \?\? "Dataset Library asset"\}, version \$\{selectedLibraryVersionId\}, into this project after durable activation revision \$\{activation\.activation_revision\}\./, "Loaded message must name the dataset, immutable version, and durable activation revision.");
assert.match(page, /setLoadedLibraryIdentity\(\{\s*datasetId: canonical\.dataset_id,\s*versionId: canonical\.dataset_version_id,?\s*\}\)/, "The exact backend-returned datasetId/versionId identity must be preserved.");

// --- Part B: Browser Session Dataset History -------------------------------

assert.doesNotMatch(page, /Browser Session Dataset History/, "The Browser Session Dataset History section must leave the primary experience.");
assert.doesNotMatch(page, /No browser-session dataset versions captured yet/, "The large empty placeholder table must not render.");
assert.match(page, /data-testid="advanced-session-details"/, "Session import records must be demoted to an Advanced session details disclosure.");
assert.match(page, /\{versions\.length > 0 && \(/, "The disclosure must not render at all when there are no records.");
// Project-scoped browser dataset isolation itself is untouched.
assert.match(page, /recordDatasetVersion\(localPayload, meta\)/, "Dataset lineage recording must be preserved.");

// --- Part C: source-aware persistence --------------------------------------

assert.match(page, /persistenceMode === "registered-status"/, "A registered asset must render a status panel instead of the persistence choice.");
assert.match(page, /View dataset provenance/, "Registered provenance must remain available without a second large summary card.");
assert.match(page, /Registered and linked to this project/, "Registered provenance title required.");
assert.match(page, /Project link" value="Current"/, "The exact project-link state must remain available in provenance.");
for (const field of ["Dataset ID", "Version ID", "Owner", "Source type"]) {
  assert.ok(page.includes(field), `Registered provenance must display ${field}`);
}
assert.match(page, /Open in Dataset Library/, "Optional Open in Dataset Library action required.");
assert.doesNotMatch(page, /Registered Dataset Library Asset/, "The former duplicate asset-summary heading must be removed.");

// The workspace/register choice still exists for genuinely unregistered data.
assert.match(page, /Project Workspace Only/, "New uploads keep the workspace-only choice.");
assert.match(page, /Register in Dataset Library/, "New uploads keep the register choice.");
assert.match(page, /data-persistence-mode=\{props\.persistenceMode\}/, "The active persistence mode must be inspectable.");

// Part C4: derived registration never implies overwriting the source.
assert.match(page, /data-testid="derived-dataset-notice"/, "Derived datasets need explicit registration language.");
assert.match(page, /it never modifies or\s*\n?\s*overwrites the immutable source version/, "Derived registration must explicitly deny overwrite.");
assert.match(page, /registrationActionLabel=\{resolveRegistrationActionLabel\(datasetSourceKind, Boolean\(datasetLibraryLink\?\.datasetId\)\)\}/, "The register button label must be source-aware.");

// Part C7: all six source states are nameable and shown.
assert.match(page, /sourceKindLabel=\{DATASET_SOURCE_LABELS\[datasetSourceKind\]\}/, "The page must always label which source state applies.");

// --- Part D + H4: readiness treatment --------------------------------------

assert.match(page, /data-testid="data-quality-readiness"/, "The readiness section must be addressable.");
assert.match(page, /border-2 border-teal-300 bg-teal-50/, "Data Quality must use a distinct light-teal readiness treatment, not flat grey.");
assert.match(page, /data-testid="readiness-status-badge"/, "A visible readiness status badge is required.");
assert.match(page, /data-readiness-status=\{status\.readiness\}/, "The shared lifecycle readiness status must be inspectable.");
assert.doesNotMatch(page, /data-testid="readiness-summary"/, "The former duplicate readiness-summary rail must remain removed.");
assert.match(page, /<ReadinessBadge status=\{acquisitionStatus\} \/>/, "The quality section must render the single shared lifecycle state.");
// Semantic tone, not uniform grey.
assert.match(page, /data-quality-tone=\{tone\}/, "Quality groups must carry a semantic tone.");
assert.match(page, /tone === "warning" \? "border-amber-300 bg-amber-50" : "border-emerald-200 bg-emerald-50"/, "Clear groups are green and warning groups amber.");
assert.match(page, /\{tone === "warning" \? "Review" : "Clear"\}/, "Status must be readable without color.");
for (const group of ["Row and column health", "Missingness and duplicates", "Predictor readiness", "Leakage screening"]) {
  assert.ok(page.includes(group), `Findings must stay visually separated: ${group}`);
}
assert.doesNotMatch(page, /Dataset identity and scope/, "Dataset identity must not be repeated inside Data Quality.");

// --- Part E: modeling rows vs preview rows ---------------------------------

assert.doesNotMatch(page, /function CurrentDatasetSummary/, "The duplicate Current Dataset Summary must remain removed.");
assert.match(page, /data-testid="browser-preview-scope-note"/, "Data Preview must retain one concise scope sentence.");
assert.match(page, /Preview limits do not change backend modeling scope/, "The preview must not imply a smaller modeling population.");

// --- Part F: authoritative event rate --------------------------------------

assert.match(page, /const serverDistribution = useTargetDistribution\(targetDistributionRequest\)/, "Target rates must come from the dedicated governed aggregate.");
assert.match(page, /scopeLabel=\{[\s\S]{0,260}?"full registered population"/, "The target distribution must disclose its governed population scope.");
assert.doesNotMatch(page, /resolveAuthoritativeEventRate\(/, "A dead preview-rate fallback must not compete with the dedicated aggregate.");
assert.doesNotMatch(page, /targetInfo\.eventRate === null[\s\S]{0,100}?formatPercent/, "The UI must not render a preview-derived target rate.");

// --- Part H1: real milestones, no fake percentage --------------------------

assert.match(progressPanel, /data-testid="dataset-load-progress"/, "The load progress panel must be addressable.");
assert.match(progressPanel, /data-stage-state=\{states\[index\]\}/, "Each milestone must expose its own state.");
assert.match(progressPanel, /aria-live="polite"/, "The active stage must be announced.");
assert.match(progressPanel, /role="status"/, "Progress must expose a status role.");
assert.match(progressPanel, /\{summary\.completed\} of \{summary\.total\} milestones/, "Progress must be reported as discrete milestones.");
assert.doesNotMatch(progressPanel, /%\}/, "No synthetic completion percentage may be rendered.");
assert.doesNotMatch(progressPanel, /toFixed\(0\)\}%/, "No synthetic completion percentage may be rendered.");
assert.match(progressPanel, /motion-safe:animate-spin/, "Motion must respect prefers-reduced-motion.");
assert.match(progressPanel, /data-testid="dataset-load-error"/, "A failed load must show an honest error.");
assert.match(page, /phase: "failed", activeStageIndex: stageIndex, failedStageIndex: stageIndex, error: detail/, "Failure must preserve completed milestones and name the failed stage.");
assert.match(page, /"Retry Load"/, "A failed load must be retryable.");

// --- Part H3: target distribution ------------------------------------------

assert.match(distributionPanel, /data-testid="target-distribution-panel"/, "The target distribution panel must be addressable.");
assert.match(distributionPanel, /import EChartsPanel/, "The production chart must render through the shared ECharts wrapper.");
assert.doesNotMatch(distributionPanel, /echarts-for-react|import \* as d3/, "No second competing chart library wrapper may be introduced.");
assert.match(distributionPanel, /Population Scale/, "Population Scale view required.");
assert.match(distributionPanel, /Rare-Event Detail/, "Rare-Event Detail view required.");
assert.match(distributionPanel, /data-testid="rare-event-scale-disclosure"/, "The adjusted-scale view must disclose that its scale is adjusted.");
assert.match(distributionPanel, /RARE_EVENT_TAKEAWAY/, "The rare-event analytical takeaway must be shown.");
assert.match(distributionPanel, /data-testid="target-distribution-summary"/, "An accessible textual summary of the chart is required.");
assert.match(distributionPanel, /describeTargetDistribution\(distribution\)/, "The accessible summary must be generated from the plotted values.");
assert.match(distributionPanel, /animation: !reducedMotion/, "Chart animation must respect reduced motion.");
assert.match(distributionPanel, /prefers-reduced-motion/, "Reduced motion must be detected.");
for (const metric of ["Event count", "Event rate", "Non-event count", "Non-event rate", "Imbalance ratio", "Total rows used", "Target column", "Positive / negative value"]) {
  assert.ok(distributionPanel.includes(metric), `Target distribution must display: ${metric}`);
}
// Aggregates come from the governed profile, never the browser preview rows.
assert.match(page, /classDistribution: quality\?\.classDistribution/, "The chart must use authoritative full-population aggregates.");

// --- Target Distribution performance: independent bounded server aggregate ----

const distributionApi = fs.readFileSync("src/lib/targetDistributionApi.ts", "utf8");
const distributionHook = fs.readFileSync("src/lib/useTargetDistribution.ts", "utf8");

assert.equal(packageJson.scripts["test:target-distribution"], "node tests/targetDistributionApi.test.mjs && .\\.venv\\Scripts\\python.exe tests\\target_distribution_test.py");
assert.equal(fs.existsSync("server/analytics/target_distribution_service.py"), true, "A dedicated bounded aggregate service must exist.");

// 1 -- the chart calls its own endpoint, not the full quality profile.
assert.match(distributionApi, /\/analytics\/target-distribution/, "The chart must call the dedicated aggregate endpoint.");
assert.doesNotMatch(distributionApi, /quality-profile/, "The chart must not depend on the full quality-profile endpoint.");

// 3 -- the panel loads independently of quality profiling.
assert.match(page, /const serverDistribution = useTargetDistribution\(targetDistributionRequest\)/, "The panel must own an independent query.");
assert.match(
  page,
  /if \(targetDistributionRequest\) \{[\s\S]{0,400}?serverDistribution\.phase === "queued"/,
  "The chart's loading state must derive from its own query, not from quality profiling."
);
assert.doesNotMatch(
  distributionHook,
  /qualityLoading|fetchFullDataQualityProfile/,
  "The target-distribution hook must not wait on quality profiling."
);

// 4 -- duplicate renders must not issue duplicate active queries.
assert.match(distributionApi, /const inFlight = new Map<string, Promise<TargetDistributionResult>>\(\)/, "In-flight requests must be de-duplicated.");
assert.match(distributionApi, /const existing = inFlight\.get\(key\);\s*\n\s*if \(existing\) return waitForSharedResult\(existing, options\.signal\);/, "A concurrent identical request must join the in-flight promise while retaining caller-local cancellation.");
assert.match(distributionApi, /function waitForSharedResult\(/, "Caller cancellation must not abort the shared aggregate query.");

// 5/6/7 -- cache keyed by the full immutable identity.
assert.match(distributionApi, /export function buildTargetDistributionKey/, "Results must be keyed by immutable identity.");
for (const dimension of ["projectId", "datasetId", "versionId", "target", "eventValue", "nonEventValue"]) {
  assert.ok(distributionApi.includes(`request.${dimension}`), `Cache identity must include ${dimension}`);
}

// 13 -- stale results cannot update a newer selection.
assert.match(distributionHook, /activeKeyRef/, "A stale-result guard is required.");
assert.match(distributionHook, /if \(activeKeyRef\.current !== key\) return;/, "Stale responses must be discarded.");

// 3/5 -- distinct, non-generic loading states.
assert.match(distributionPanel, /Calculating target distribution from the registered dataset\.\.\./, "The chart must show a bounded, specific loading message.");
for (const phase of ["queued", "running", "cached", "exact", "sampled", "failed"]) {
  assert.ok(distributionPanel.includes(`${phase}:`) || distributionPanel.includes(`"${phase}"`), `Query state must distinguish: ${phase}`);
}
assert.match(distributionPanel, /data-query-phase=\{query\.phase\}/, "The active query phase must be inspectable.");

// 9/10 -- sampled results are disclosed and never labelled exact.
assert.match(distributionPanel, /Estimated from stratified sample/, "A sampled estimate must be labelled as such.");
assert.match(distributionPanel, /data-testid="sampled-estimate-disclosure"/, "Sampling disclosure required.");
assert.match(distributionPanel, /These are\s*\n?\s*estimates, not exact population counts\./, "Sampled counts must never be presented as exact.");
assert.match(distributionPanel, /Calculate Exact Distribution/, "A Calculate Exact Distribution action is required.");

// 12 -- failures are retryable.
assert.match(distributionPanel, /data-testid="retry-target-distribution"/, "A failed query must be retryable.");

// 6 (server) -- the full target column never leaves the server.
const distributionService = fs.readFileSync("server/analytics/target_distribution_service.py", "utf8");
assert.match(distributionService, /GROUP BY 1 ORDER BY count DESC LIMIT/, "The aggregate must be a bounded grouped count.");
assert.match(distributionService, /MAX_TARGET_CARDINALITY/, "Result cardinality must be bounded.");
assert.match(distributionService, /def _quote_identifier/, "The target identifier must be quoted.");
assert.doesNotMatch(distributionService, /SELECT \* FROM/, "The service must never select the full row set.");
// Sampling is a fallback, never the default for rare-event targets.
assert.match(distributionService, /def _should_sample/, "Sampling must be an explicit planner decision.");
assert.match(distributionService, /if force_exact:\s*\n\s*return False/, "Calculate Exact Distribution must override sampling.");
assert.match(distributionService, /deterministic_stratified/, "The fallback must be deterministic stratified sampling.");
assert.match(distributionService, /SAMPLE_SEED/, "Sampling must use an explicit seed.");
assert.doesNotMatch(distributionPanel, /previewRows|profilingRows/, "The chart must not be computed from browser preview rows.");
assert.match(page, /targetDistributionState/, "The chart must support loading/empty/error/unsupported states.");

// --- Part H2: readiness track ----------------------------------------------

for (const stage of ["Registered", "Linked", "Version loaded", "Target confirmed", "Predictor authorization", "Partition current"]) {
  assert.ok(page.includes(stage), `The canonical Data Contract must include status: ${stage}`);
}
assert.match(page, /<DataContractStatusChips/, "One compact lifecycle status surface must replace the former readiness track.");

// --- Part H6: visual hierarchy ---------------------------------------------

assert.match(page, /data-testid="source-command-section"/, "The source-and-load command section needs its own identity.");
assert.match(page, /border-2 border-slate-400 bg-slate-100/, "The command section must be strongly tinted, not flat white.");
assert.match(page, /data-testid="data-acquisition-target-setup"/, "Target selection needs a stable, prominent decision surface.");
assert.match(page, /Required modeling decision/, "Target selection must state that it is required.");
assert.match(page, /Identify the Target Variable/, "Target selection needs an explicit action-oriented heading.");
assert.match(page, /data-testid="target-column-search"/, "Target selection must support searching large feature sets.");
assert.match(page, /Search target columns/, "The target-column search must be explicitly labeled.");
assert.match(page, /border-2 border-blue-500/, "Target selection must visually stand apart from surrounding source controls.");
assert.match(page, /Target contract confirmed: \$\{props\.target\}/, "The selected target must remain visible as confirmed state.");
assert.match(distributionPanel, /border-2 border-blue-300 bg-blue-50/, "Target Setup / Distribution must use a light-blue identity.");

// --- Performance: no full dataset transfer ---------------------------------

assert.doesNotMatch(distributionPanel, /duckdb|DuckDB/, "DuckDB-Wasm must not be initialized for simple target-distribution aggregates.");
assert.match(page, /browserComplete: false/, "Library loads must keep the browser to a preview, never the full dataset.");

console.log("dataAcquisitionUx.test.mjs: all checks passed.");
