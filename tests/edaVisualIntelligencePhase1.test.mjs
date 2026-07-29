import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";

const read = (path) => readFile(new URL(`../${path}`, import.meta.url), "utf8");

const [
  step,
  distribution,
  correlation,
  vif,
  selection,
  motion,
  router,
  service,
  workspaceTypes,
] = await Promise.all([
  read("src/steps/Step02_EDA.tsx"),
  read("src/components/eda/visual/PredictorDistributionExplorer.tsx"),
  read("src/components/eda/visual/CorrelationExplorer.tsx"),
  read("src/components/eda/visual/VifExplorer.tsx"),
  read("src/state/useEdaVisualSelection.ts"),
  read("src/visual-intelligence/motion.ts"),
  read("server/eda/eda_router.py"),
  read("server/eda/workspace_service.py"),
  read("server/eda/workspace_types.py"),
]);

function sourceBetween(source, start, end) {
  const startIndex = source.indexOf(start);
  assert.notEqual(startIndex, -1, `Expected source marker: ${start}`);
  const endIndex = source.indexOf(end, startIndex + start.length);
  assert.notEqual(endIndex, -1, `Expected source marker after ${start}: ${end}`);
  return source.slice(startIndex, endIndex);
}

// Phase 1 runtime integration and shared linked-selection scope.
assert.match(step, /<PredictorDistributionExplorer/);
assert.match(step, /<CorrelationExplorer/);
assert.match(step, /<VifExplorer/);
assert.doesNotMatch(step, /<DistributionExplorer/);
assert.doesNotMatch(step, /<VisualAnalysisPanel/);
assert.doesNotMatch(step, /eda\/histogram\/\$\{/);
assert.match(step, /data-testid="eda-predictor-authorization"/);
assert.match(step, /data-testid="eda-linked-selection-summary"/);
assert.match(step, /setSelectionScope\(`\$\{projectId\}:\$\{overview\.dataset_version\}:\$\{overview\.target\}`\)/);
assert.match(step, /props\.onRun\(\{ pairwise_features: nextPairwise \}\)/);
assert.match(step, /data-testid="pairwise-linked-range"/);
assert.match(step, /selectedRange=\{selectedRange\}/);
assert.match(step, /rows=\{safeArray<any>\(props\.data\.target_association\)\}/);

// Predictor Distribution Explorer: one governed POST contract, exact aggregate
// overlays, keyed motion, range/quantile linkage, and accessible fallbacks.
assert.match(distribution, /fetch\(`\$\{API_BASE\}\/eda\/workspace\/distribution`/);
assert.match(distribution, /method: "POST"/);
assert.match(distribution, /credentials: "include"/);
assert.match(distribution, /const distributionRequests = new Map<string, CacheEntry>\(\)/);
assert.match(distribution, /existing && now - existing\.createdAt < REQUEST_CACHE_MS/);
assert.match(distribution, /requestKey\(\{ \.\.\.body, dataset_version: datasetVersion \}\)/);
assert.match(distribution, /const MAX_REQUEST_CACHE_ENTRIES = 48/);
assert.match(distribution, /selected_features: available/);
assert.match(distribution, /selection_min: activeRange\.min, selection_max: activeRange\.max/);
assert.doesNotMatch(distribution, /d3_histogram|sample_pct|\/eda\/histogram\//);
assert.match(distribution, /new ResizeObserver\(update\)/);
assert.match(distribution, /\.data\(data\.bins, \(row\) => String\(row\.bin\)\)/);
assert.match(distribution, /\.brushX<null>\(\)/);
assert.match(distribution, /runAtlasD3Transition/);
assert.match(distribution, /useReducedMotion/);
assert.match(distribution, /data-motion-phase=\{motionPhase\}/);
assert.match(distribution, /Linked quantile view/);
assert.match(distribution, /setSelectedQuantile\(\{/);
assert.match(distribution, /data-testid="eda-missing-bucket"/);
assert.match(distribution, /data-testid="eda-iv-by-bin-toggle"/);
assert.match(distribution, /Export current bins/);
assert.match(distribution, /Use Tab to focus bins, Enter to select a bin/);
for (const overlay of [
  "showDensity",
  "showEventRate",
  "showOutliers",
  "markers.mean",
  "markers.median",
  "missing_bucket",
  "iv_by_bin",
]) {
  assert.ok(distribution.includes(overlay), `Distribution explorer is missing ${overlay}.`);
}

// Correlation Explorer: bounded rendering, deterministic clustering, filtering,
// keyed enter/update/exit, pinning, export, and keyboard/table accessibility.
assert.match(correlation, /const MAX_SUBSET_LIMIT = 50/);
assert.match(correlation, /export function clusterCorrelationColumns/);
assert.match(correlation, /type MatrixOrder = "original" \| "alphabetical" \| "clustered"/);
assert.match(correlation, /setAbsoluteThreshold/);
assert.match(correlation, /\.data\(cells, \(cell\) => cell\.key\)/);
assert.match(correlation, /runAtlasD3Transition/);
assert.match(correlation, /actionRef\.current\.onPinPair\(\{ a: cell\.row\.name, b: cell\.column\.name \}\)/);
assert.match(correlation, /event\.key !== "Enter" && event\.key !== " "/);
assert.match(correlation, /Export current matrix/);
assert.match(correlation, /data-testid="correlation-matrix-svg"/);
assert.match(correlation, /Accessible data table/);
assert.match(correlation, /Use Tab to focus visible cells and Enter to pin/);
assert.match(correlation, /prefers-reduced-motion: reduce/);

// VIF Explorer: review-only thresholds, version-scoped decisions, strongest
// relationship linkage, and a non-mutating server-side what-if contract.
assert.match(vif, /VIF 5–&lt;10 and VIF ≥10 are review thresholds, not automatic removal/);
assert.match(vif, /const DECISION_STORAGE_PREFIX = "atlas\.eda\.vif-decisions"/);
assert.match(vif, /decisionStorageKey\(datasetVersion\)/);
assert.match(vif, /window\.localStorage\.setItem/);
assert.match(vif, /"retain" \| "drop" \| "combine"/);
assert.match(vif, /function strongestPartners/);
assert.match(vif, /mode: "temporary-exclusion"/);
assert.match(vif, /temporarilyExcludedVariables: \[activeVariable\]/);
assert.match(vif, /Runs an analytical preview without changing the dataset, approved\s+predictor manifest, or recorded decision/);
assert.match(vif, /data-testid="vif-simulator"/);
assert.match(vif, /data-testid="vif-decision-capture"/);
assert.match(vif, /data-testid="vif-partner-list"/);
assert.match(vif, /VIF analysis data table/);
assert.match(vif, /data-testid="vif-scope-badge"/);
assert.match(vif, /Export current table/);
assert.match(vif, /hardenCsvCell/);
assert.match(vif, /useReducedMotion/);
assert.match(vif, /ATLAS_MOTION_TOKENS/);

// Shared store behavior: changing scope resets stale selections, choosing a
// quantile creates the equivalent range, and Clear Selection preserves only
// the active variable context.
const selectionImplementation = selection.slice(
  selection.indexOf("export const useEdaVisualSelection"),
);
const setScopeReducer = sourceBetween(selectionImplementation, "setScope: (scopeKey)", "setSelectedVariable:");
assert.match(setScopeReducer, /state\.scopeKey === scopeKey/);
assert.match(setScopeReducer, /\.\.\.EMPTY_SELECTION/);

const quantileReducer = sourceBetween(selectionImplementation, "setSelectedQuantile:", "pinPair:");
assert.match(quantileReducer, /selectedRange: selectedQuantile/);
assert.match(quantileReducer, /source: "quantile"/);
assert.match(quantileReducer, /Math\.min\(selectedQuantile\.min, selectedQuantile\.max\)/);
assert.match(quantileReducer, /Math\.max\(selectedQuantile\.min, selectedQuantile\.max\)/);

const clearReducer = sourceBetween(selectionImplementation, "clearSelection:", "reset:");
assert.match(clearReducer, /selectedVariable: state\.selectedVariable/);
for (const clearedField of [
  "selectedRange: null",
  "selectedQuantile: null",
  "pinnedPair: null",
  "vifVariable: null",
  "hover: null",
]) {
  assert.ok(clearReducer.includes(clearedField), `Clear Selection must clear ${clearedField}.`);
}
assert.match(selection, /setVifVariable:[\s\S]*selectedVariable: vifVariable/);
assert.match(selection, /type EdaVisualHover[\s\S]*kind: "pair"[\s\S]*kind: "range"/);

// Shared motion contract remains centralized rather than scattered constants.
assert.match(motion, /export const ATLAS_MOTION_TOKENS/);
assert.match(motion, /enter: 560/);
assert.match(motion, /update: 320/);
assert.match(motion, /highlight: 140/);
assert.match(motion, /maxTotalMs: 180/);
assert.match(motion, /environment\.reducedMotion[\s\S]*"reduced-motion"/);
assert.match(motion, /const durationMs = enabled \? ATLAS_MOTION_TOKENS\.durationMs\[kind\] : 0/);

// Server authorization is the source of truth. Browser feature lists can only
// narrow the already-filtered frame; target and deterministic target sources
// never reach Phase 1 visual calculations.
assert.match(service, /def _predictor_authorization/);
assert.match(service, /governed_target = str\(DATASTORE\.target or ""\)\.strip\(\)/);
assert.match(service, /requested target does not match the server-governed modeling target/);
assert.match(service, /authorization\["authorized_predictors"\]/);
assert.match(service, /df = active\.loc\[:, \[\*keep, target\]\]\.copy\(\)/);
assert.match(service, /"target_source_excluded": sorted\(target_sources\)/);
assert.match(service, /"rejected_requested_features": \[/);
assert.match(service, /"distribution": self\._distribution/);
assert.match(service, /feature == target or feature not in df\.columns/);
assert.match(service, /engine": "server_numpy_full_population"/);
assert.match(service, /"resolution": "exact"/);
assert.match(service, /candidate_columns = request\.selected_features or/);
assert.match(service, /if column not in df\.columns or column == target/);
assert.match(service, /excluded not in authorization\["authorized_predictors"\]/);
assert.match(service, /"non_mutating": True/);

const histogramRoute = sourceBetween(
  router,
  '@router.get("/histogram/{column}")',
  '@router.get("/boxplot/{column}")',
);
assert.match(histogramRoute, /eda_workspace_service\.section\(\s*"distribution"/);
assert.match(histogramRoute, /target=DATASTORE\.target/);
assert.match(histogramRoute, /status_code=422/);
assert.doesNotMatch(histogramRoute, /_require_df\(\)|eda_service\.histogram/);

const correlationRoute = sourceBetween(
  router,
  '@router.get("/correlation")',
  '@router.get("/sample")',
);
assert.match(correlationRoute, /eda_workspace_service\.section\(\s*"relationships"/);
assert.match(correlationRoute, /target=DATASTORE\.target/);
assert.doesNotMatch(correlationRoute, /_require_df\(\)|eda_service\.correlation/);

assert.match(router, /@router\.post\("\/vif-simulation"\)/);
assert.match(workspaceTypes, /feature: Optional\[str\] = None/);
assert.match(workspaceTypes, /selection_min: Optional\[float\] = None/);
assert.match(workspaceTypes, /selection_max: Optional\[float\] = None/);
assert.match(workspaceTypes, /class EDAVifSimulationRequest/);

console.log("edaVisualIntelligencePhase1.test.mjs: all checks passed.");
