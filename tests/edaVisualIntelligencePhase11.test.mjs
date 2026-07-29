import assert from "node:assert/strict";
import { webcrypto } from "node:crypto";
import { readFile, readdir } from "node:fs/promises";
import { fileURLToPath } from "node:url";
import vm from "node:vm";
import ts from "typescript";

const read = async (path) =>
  (await readFile(new URL(`../${path}`, import.meta.url), "utf8")).replace(
    /\r\n/g,
    "\n",
  );

const [
  distribution,
  correlation,
  relationship,
  relationshipWebGl,
  selection,
  step,
  codeSafety,
  pythonPanel,
  codeWorkspace,
  notebookExport,
  workspaceTypes,
  workspaceService,
  router,
  packageSource,
] = await Promise.all([
  read("src/components/eda/visual/PredictorDistributionExplorer.tsx"),
  read("src/components/eda/visual/CorrelationExplorer.tsx"),
  read("src/components/eda/visual/RelationshipExplorer.tsx"),
  read("src/components/eda/visual/RelationshipWebGL.tsx"),
  read("src/state/useEdaVisualSelection.ts"),
  read("src/steps/Step02_EDA.tsx"),
  read("src/lib/codeContextSafety.ts"),
  read("src/components/StepPythonPanel.tsx"),
  read("src/components/code/CodeWorkspacePanel.tsx"),
  read("src/lib/notebookExport.ts"),
  read("server/eda/workspace_types.py"),
  read("server/eda/workspace_service.py"),
  read("server/eda/eda_router.py"),
  read("package.json"),
]);

const packageJson = JSON.parse(packageSource);
const failures = [];
let checkCount = 0;

function check(name, callback) {
  checkCount += 1;
  try {
    callback();
    console.log(`ok ${checkCount} - ${name}`);
  } catch (error) {
    failures.push({ name, error });
    console.error(`not ok ${checkCount} - ${name}`);
  }
}

function sourceBetween(source, start, end, label = start) {
  const startIndex = source.indexOf(start);
  assert.notEqual(startIndex, -1, `${label}: missing start marker ${start}`);
  const endIndex = source.indexOf(end, startIndex + start.length);
  assert.notEqual(endIndex, -1, `${label}: missing end marker ${end}`);
  return source.slice(startIndex, endIndex);
}

function assertIncludes(source, values, label) {
  for (const value of values) {
    assert.ok(source.includes(value), `${label}: missing ${JSON.stringify(value)}`);
  }
}

async function walkSource(directoryUrl) {
  const entries = await readdir(directoryUrl, { withFileTypes: true });
  const files = [];
  for (const entry of entries) {
    const child = new URL(
      `${encodeURIComponent(entry.name)}${entry.isDirectory() ? "/" : ""}`,
      directoryUrl,
    );
    if (entry.isDirectory()) {
      files.push(...(await walkSource(child)));
    } else if (/\.[cm]?[jt]sx?$/.test(entry.name)) {
      files.push(child);
    }
  }
  return files;
}

const sourceFiles = await walkSource(new URL("../src/", import.meta.url));
const echartsGlImporters = [];
for (const sourceFile of sourceFiles) {
  const contents = await readFile(sourceFile, "utf8");
  if (contents.includes("echarts-gl")) {
    echartsGlImporters.push(
      fileURLToPath(sourceFile).replace(/\\/g, "/").split("/src/")[1],
    );
  }
}

const STABILITY_NOTE =
  "This dataset does not contain a governed observation-time or reusable segment field. Stability analysis can be enabled with a documented date, cohort, product, region, channel, or other approved segmentation variable.";
const STALE_CODE_WARNING =
  "This edited code was created for a different dataset or target.";

check("Stability stays honest and does not block EDA when fields are absent", () => {
  assert.ok(step.includes(STABILITY_NOTE), "The required Stability note must be exact.");
  const stabilityState = sourceBetween(
    step,
    "!hasTimeFields && !hasSegmentFields",
    '<div className="grid gap-4 xl:grid-cols-2">',
    "Stability empty state",
  );
  assert.match(stabilityState, /No governed time or segment fields were detected/);
  assert.match(stabilityState, /!hasTimeProfile && !hasSegmentProfile/);
  assert.doesNotMatch(stabilityState, /throw|disabled|block completion/i);
});

check("Predictor metrics use a semantic readable 2-by-4 layout", () => {
  assert.match(
    distribution,
    /<dl\s+className="grid grid-cols-2 gap-3 sm:grid-cols-4"[\s\S]*?data-testid="eda-predictor-metric-grid"/,
  );
  assertIncludes(
    distribution,
    [
      'label="Selected rows"',
      'label="Population share"',
      'label="Selected mean"',
      'label="Selected median"',
      'label="Selected range"',
      "IQR (Q1",
      '"Selected target rate"',
      "selected_subset.q1",
      "selected_subset.q3",
    ],
    "Predictor metric grid",
  );
  const metricComponent = sourceBetween(
    distribution,
    "function Metric(",
    "function MarkerPill(",
    "Metric component",
  );
  assert.match(metricComponent, /<dt[\s\S]*<dd/);
  assert.match(metricComponent, /text-xl[\s\S]*sm:text-2xl/);
  assert.match(metricComponent, /break-words/);
  assert.doesNotMatch(metricComponent, /\btruncate\b/);
});

check("Linked quantiles default to at most five cards and expose readable values", () => {
  assert.match(
    distribution,
    /quantileDisplayMode[\s\S]{0,180}"compact" \| "expanded"[\s\S]{0,80}>\("compact"\)/,
  );
  assert.match(
    distribution,
    /quantileDisplayMode === "compact"[\s\S]{0,120}"lg:grid-cols-3 xl:grid-cols-5"[\s\S]{0,100}"lg:grid-cols-3"/,
  );
  assertIncludes(
    distribution,
    [
      'data-testid="eda-quantile-display-mode"',
      'data-testid="eda-quantile-grid"',
      'data-display-mode={quantileDisplayMode}',
      "Event rate",
      "Band range",
      "Rows",
      "Lift vs population",
      "formatLift(row.event_rate, populationEventRate)",
      "min-h-[9rem] p-3",
      "min-h-[11rem] p-4",
      "aria-pressed={pinned}",
      "setSelectedQuantile({",
      "focus-visible:ring-2",
      "motion-reduce:transition-none",
    ],
    "Linked quantile view",
  );
  assert.match(distribution, /pinned[\s\S]{0,180}border-blue-800 bg-blue-700/);
  assert.match(
    sourceBetween(
      distribution,
      "function formatLift(",
      "function populationVisualSignature(",
      "Quantile lift",
    ),
    /eventRate \/ populationEventRate/,
  );
});

check("Histogram brush synchronization does not replay the main D3 render", () => {
  const mainRender = sourceBetween(
    distribution,
    "useEffect(() => {\n    if (!svgRef.current || !data?.bins.length || width <= 0) return;",
    "  useEffect(() => {\n    if (!svgRef.current || !data?.bins.length) return;",
    "Distribution main render effect",
  );
  const brushSync = sourceBetween(
    distribution,
    "useEffect(() => {\n    if (!svgRef.current || !data?.bins.length) return;",
    "  useEffect(() => {\n    if (!svgRef.current) return;",
    "Distribution brush synchronization effect",
  );
  assertIncludes(
    mainRender,
    [
      ".brushX<null>()",
      "brushRef.current = brush",
      "brushScaleRef.current = x",
    ],
    "Distribution main render effect",
  );
  assert.doesNotMatch(
    mainRender,
    /\bactiveRange\b/,
    "The full chart effect must not depend on linked range changes.",
  );
  assertIncludes(
    brushSync,
    [
      "brushRef.current",
      "brushScaleRef.current",
      "brush.move",
      "activeRange.min",
      "activeRange.max",
    ],
    "Distribution brush synchronization effect",
  );
  assert.match(
    distribution,
    /setChartData\(\(current\) =>[\s\S]*populationVisualSignature\(current\) === populationVisualSignature\(payload\)[\s\S]*\? current[\s\S]*: payload/,
  );
  assert.match(distribution, /<DistributionChart[\s\S]*data=\{displayChartData\}/);
});

check("Correlation defaults and cell typography remain readable", () => {
  const defaultMatch = correlation.match(/const DEFAULT_SUBSET_LIMIT = (\d+);/);
  const cellMatch = correlation.match(/const BASE_CELL_SIZE = (\d+);/);
  assert.ok(defaultMatch, "Correlation default subset constant is missing.");
  assert.ok(cellMatch, "Correlation base cell-size constant is missing.");
  assert.ok(
    [10, 12].includes(Number(defaultMatch[1])),
    "Correlation must default to 10 or 12 variables.",
  );
  assert.ok(Number(cellMatch[1]) >= 48, "Correlation cells must remain readable.");
  assert.match(correlation, /const MAX_SUBSET_LIMIT = 50/);
  assert.match(correlation, /Up to \{value\}/);
  assert.match(
    correlation,
    /\.attr\(\s*"font-size",\s*Math\.max\(10, Math\.min\(14, dimensions\.cellSize \* 0\.25\)\)/,
  );
  assert.match(correlation, /relative overflow-auto overscroll-contain/);
  assert.doesNotMatch(correlation, /grid-cols-20|w-\[.*\/20\]/);
});

check("Correlation expanded mode is accessible and restores focus", () => {
  assertIncludes(
    correlation,
    [
      "Expand matrix",
      "Exit expanded",
      'role={isExpanded ? "dialog" : undefined}',
      "aria-modal={isExpanded ? true : undefined}",
      "data-expanded={String(isExpanded)}",
      'event.key === "Escape"',
      'document.body.style.overflow = "hidden"',
      "returnFocusRef.current?.focus()",
    ],
    "Expanded correlation matrix",
  );
  assert.match(correlation, /fixed inset-3 z-\[80\][\s\S]*sm:inset-6/);
});

check("Correlation zoom, sticky labels, and retained analysis controls are wired", () => {
  assertIncludes(
    correlation,
    [
      'aria-label="Zoom out correlation matrix"',
      'aria-label="Zoom in correlation matrix"',
      "Fit matrix",
      'aria-label="Reset correlation matrix zoom and scroll"',
      'data-testid="correlation-sticky-labels"',
      'data-testid="correlation-sticky-column-labels"',
      'data-testid="correlation-sticky-row-labels"',
      "Find a variable",
      "Absolute threshold",
      "Matrix order",
      "Export current matrix",
      '.data(cells, (cell) => cell.key)',
    ],
    "Correlation controls",
  );
  assert.match(correlation, /prefers-reduced-motion: reduce/);
});

check("Pinned pairs expose full names, exact statistics, sample N, VIF, and launches", () => {
  const pinnedPanel = sourceBetween(
    correlation,
    "{pinnedDetail ? (",
    "<details className=",
    "Pinned correlation detail",
  );
  assertIncludes(
    pinnedPanel,
    [
      "pinnedDetail.pair.a",
      "pinnedDetail.pair.b",
      '"Exact correlation"',
      '"Sign"',
      '"Pairwise N"',
      "pinnedDetail.sampleSize",
      "pinnedDetail.leftVif",
      "pinnedDetail.rightVif",
      "Launch 2D scatter",
      "Launch 3D explorer",
      "break-words",
    ],
    "Pinned correlation detail",
  );
  assert.match(correlation, /correlationSampleSizes/);
  assert.match(correlation, /readSampleSize\(/);
  const accessibleTable = sourceBetween(
    correlation,
    "Accessible data table",
    "</details>",
    "Correlation accessible table",
  );
  assertIncludes(
    accessibleTable,
    [
      "title={column.name}",
      "{column.name}",
      "title={row.name}",
      "{row.name}",
      "whitespace-normal break-words",
      "sticky top-0",
      "sticky left-0",
    ],
    "Correlation accessible table",
  );
});

check("WebGL remains isolated behind both EDA and 3D lazy boundaries", () => {
  assert.match(
    step,
    /const RelationshipExplorer = React\.lazy\([\s\S]*import\("\.\.\/components\/eda\/visual\/RelationshipExplorer"\)/,
  );
  assert.match(
    step,
    /data-testid="eda-relationship-explorer-section"[\s\S]*<React\.Suspense[\s\S]*<RelationshipExplorer/,
  );
  assert.doesNotMatch(
    step,
    /relationshipExplorerOpen/,
    "The first-class Relationship Explorer must not be hidden behind disclosure state.",
  );
  assert.match(
    relationship,
    /const RelationshipWebGL = lazy\(\(\) => import\("\.\/RelationshipWebGL"\)\)/,
  );
  assert.doesNotMatch(relationship, /from "\.\/RelationshipWebGL"/);
  assert.doesNotMatch(relationship, /echarts-gl/);
  assert.deepEqual(
    echartsGlImporters.filter((path) => !path.endsWith(".d.ts")),
    ["components/eda/visual/RelationshipWebGL.tsx"],
    "echarts-gl may only be imported at runtime by the lazily rendered WebGL module.",
  );
  assertIncludes(
    relationshipWebGl,
    [
      'from "echarts-gl/charts"',
      'from "echarts-gl/components"',
      "Scatter3DChart",
      "Grid3DComponent",
    ],
    "Relationship WebGL module",
  );
  assert.equal(
    packageJson.dependencies?.["echarts-gl"],
    "2.1.0",
    "echarts-gl must stay pinned to the reviewed exact version.",
  );
});

check("Relationship Explorer offers governed controls, preserved modes, and explicit Z", () => {
  assertIncludes(
    relationship,
    [
      "Governed visual sample",
      "X axis",
      "Y axis",
      "Z axis",
      "explicitly selected",
      "Point size",
      "optional",
      "Target group",
      "No grouping",
      "Approved segment",
      "Rendered rows",
      "device cap",
      "Point opacity",
      "2D Scatter",
      "Density",
      "3D Explorer",
      "Grid",
      "Legend",
      "Rotate left",
      "Rotate right",
      "Zoom in",
      "Zoom out",
      "Pan left",
      "Pan right",
      "Reset camera",
      "mode === \"3d\" && !axes.z",
    ],
    "Relationship controls",
  );
  assert.match(relationship, /setMode\(nextMode\)/);
  assert.doesNotMatch(
    sourceBetween(
      relationship,
      "const activateMode = useCallback(",
      "useEffect(() => {\n    if (\n      mode === \"3d\"",
      "Relationship mode activation",
    ),
    /setAxes|setSelectedRange/,
    "Switching relationship modes must preserve axes and linked range state.",
  );
});

check("Relationship requests are bounded, identity-keyed, and promise-deduplicated", () => {
  const requestSignature = sourceBetween(
    relationship,
    "const requestSignature = useMemo",
    "  useEffect(() => {\n    if (!requestSignature)",
    "Relationship request signature",
  );
  assertIncludes(
    requestSignature,
    [
      "project_id: projectId",
      "target",
      "dataset_version: datasetVersion",
      "predictor_manifest_id: predictorManifestId",
      "x_feature: axes.x",
      "y_feature: axes.y",
      "z_feature: axes.z || undefined",
      "selection_feature:",
      "sample_limit: Math.min(sampleLimit, sampleCap)",
    ],
    "Relationship request signature",
  );
  assertIncludes(
    relationship,
    [
      "const responseCache = new Map<string, Promise<RelationshipSampleResponse>>()",
      "responseCache.get(requestSignature)",
      "if (!request)",
      "boundedCacheSet(requestSignature, request)",
      "responseCache.delete(requestSignature)",
      'fetch(`${API_BASE}/eda/relationship-sample`',
      'method: "POST"',
      'credentials: "include"',
    ],
    "Relationship request de-duplication",
  );
});

check("Launching an already pinned pair does not repeat the pairwise analytical request", () => {
  const launchBlock = sourceBetween(
    step,
    "const launchRelationshipExplorer = useCallback(",
    "\n\n  return (",
    "Relationship launch callback",
  );
  assertIncludes(
    launchBlock,
    [
      "const alreadyPinned",
      "pinnedPair.a === pair.a && pinnedPair.b === pair.b",
      "pinnedPair.a === pair.b && pinnedPair.b === pair.a",
      "if (pair && !alreadyPinned) handlePinnedPair(pair)",
    ],
    "Already-pinned pair guard",
  );
  assert.doesNotMatch(
    launchBlock,
    /props\.onRun/,
    "The launch callback must delegate at most one guarded pairwise refresh.",
  );
});

check("Relationship scope, export, table fallback, and analytical caveat stay visible", () => {
  assertIncludes(
    relationship,
    [
      "Export sample",
      "Export state",
      "sampleLimit: Math.min(sampleLimit, sampleCap)",
      "camera",
      "selectedRange",
      "populationRows: response.population_rows",
      "returnedRows: response.returned_rows",
      '"target_group"',
      "Accessible rendered-sample table",
      "Raw target values are not",
      "Population",
      "Complete-case eligible",
      "Rendered sample",
      "Linked range overlap",
      "deterministically",
      "does not establish predictor usefulness or",
      "model quality",
    ],
    "Relationship scope and exports",
  );
  const csvExport = sourceBetween(
    relationship,
    "const exportSample = () =>",
    "  const axisOption = (",
    "Relationship sample export",
  );
  assert.match(csvExport, /target_group/);
  assert.doesNotMatch(csvExport, /response\.target\b|point\.target\b/);
});

check("3D reduced motion, linked highlighting, and context-loss fallback are enforced", () => {
  assertIncludes(
    relationship,
    [
      "useReducedMotion()",
      "if (reducedMotion && camera.autoRotate)",
      "disabled={reducedMotion}",
      "checked={!reducedMotion && camera.autoRotate}",
      "inLinkedRange(point, selectedRange)",
      "selection_feature === selectedRange.feature",
      "setWebglFailed(true)",
      'setMode("2d")',
      "WebGL is unavailable or its context was lost.",
      "Use 2D fallback",
      "<Suspense",
      "<RelationshipWebGL",
    ],
    "Relationship fallback and reduced motion",
  );
  assertIncludes(
    relationshipWebGl,
    [
      "animation: !reducedMotion",
      "autoRotate: reducedMotion ? false : camera.autoRotate",
      "damping: reducedMotion ? 0 : 0.8",
      'type: "scatter3D"',
      "inLinkedRange(point, selectedRange)",
      'canvas?.addEventListener("webglcontextlost", handleContextLost)',
      'canvas?.removeEventListener("webglcontextlost", handleContextLost)',
      "onContextLost()",
      'role="img"',
      "Interactive 3D relationship plot",
    ],
    "Relationship WebGL behavior",
  );
});

check("Linked state populates axes, preserves range context, and clears coherently", () => {
  const selectionImplementation = selection.slice(
    selection.indexOf("export const useEdaVisualSelection"),
  );
  const variableReducer = sourceBetween(
    selectionImplementation,
    "setSelectedVariable:",
    "setSelectedRange:",
    "Selected-variable reducer",
  );
  assertIncludes(
    variableReducer,
    [
      'source === "correlation"',
      'source === "vif"',
      'source === "pairwise"',
      'source === "relationship3d"',
      "selectedRange: preserveLinkedRange ? state.selectedRange : null",
    ],
    "Linked-range preservation",
  );
  const pairReducer = sourceBetween(
    selectionImplementation,
    "pinPair:",
    "setVifVariable:",
    "Pinned-pair reducer",
  );
  assertIncludes(
    pairReducer,
    [
      "x: pinnedPair.a",
      "y: pinnedPair.b",
      "state.relationshipAxes.z",
    ],
    "Pinned-pair axes",
  );
  const vifReducer = sourceBetween(
    selectionImplementation,
    "setVifVariable:",
    "setRelationshipAxes:",
    "VIF linkage reducer",
  );
  assert.match(vifReducer, /x: vifVariable/);
  const modeReducer = sourceBetween(
    selectionImplementation,
    "setRelationshipMode:",
    "setHover:",
    "Relationship mode reducer",
  );
  assert.doesNotMatch(modeReducer, /relationshipAxes|selectedRange/);
  const clearReducer = sourceBetween(
    selectionImplementation,
    "clearSelection:",
    "reset:",
    "Clear Selection reducer",
  );
  assertIncludes(
    clearReducer,
    [
      "selectedVariable: state.selectedVariable",
      "selectedRange: null",
      "selectedQuantile: null",
      "pinnedPair: null",
      "vifVariable: null",
      "relationshipAxes: { x: null, y: null, z: null }",
      'relationshipMode: "2d"',
    ],
    "Clear Selection reducer",
  );
});

check("Step 02 connects heatmap, VIF, brushing, clear, and governed code identity", () => {
  assertIncludes(
    step,
    [
      "correlationSampleSizes={safeArray<Array<number | null>>(",
      "props.data.correlation_n_matrix",
      "vifByFeature={vifByFeature}",
      "onLaunch2D={(pair) => launchRelationshipExplorer(\"2d\", pair)}",
      "onLaunch3D={(pair) => launchRelationshipExplorer(\"3d\", pair)}",
      "selectedRange={selectedRange}",
      "initialPair={pinnedPair}",
      "vifVariable={vifVariable}",
      "Clear selection",
      "clearVisualSelection",
      "writeEdaCodeContextSeed(projectId, {",
      "datasetId:",
      "datasetVersion:",
      "datasetName:",
      "target:",
      "predictorManifestId:",
      "generatedAt:",
    ],
    "Step 02 Phase 1.1 wiring",
  );
});

check("Relationship request type and router are bounded and fail closed", () => {
  const requestType = workspaceTypes.slice(
    workspaceTypes.indexOf("class EDARelationshipSampleRequest"),
  );
  assert.ok(
    requestType.startsWith("class EDARelationshipSampleRequest"),
    "Relationship request type is missing.",
  );
  assertIncludes(
    requestType,
    [
      "server-authored",
      "cannot add the target",
      "x_feature: str",
      "y_feature: str",
      "z_feature: Optional[str]",
      "point_size_feature: Optional[str]",
      "segment_feature: Optional[str]",
      "selection_feature: Optional[str]",
      "sample_limit: int = Field(default=2500, ge=100, le=5000)",
    ],
    "Relationship request type",
  );
  const relationshipRoute = sourceBetween(
    router,
    '@router.post("/relationship-sample")',
    '@router.post("/profile")',
    "Relationship router",
  );
  assertIncludes(
    relationshipRoute,
    [
      'authorize_modeling_scope(user, request.project_id, "view")',
      "eda_workspace_service.relationship_sample(request)",
      "RelationshipSampleValidationError",
      "status_code=422",
      '"relationship_fields_not_authorized"',
      '"rejected_fields"',
      '"relationship_context_mismatch"',
      "status == 409",
    ],
    "Relationship router",
  );
});

check("Backend relationship sample authorizes every field and keys the bounded cohort", () => {
  const relationshipService = sourceBetween(
    workspaceService,
    "    def relationship_sample(",
    "    def _full_population_assessment(",
    "Relationship sample service",
  );
  assertIncludes(
    relationshipService,
    [
      "self._dataset(base)",
      'authorization["authorized_predictors"]',
      "field not in authorized or field not in df.columns",
      "RelationshipSampleValidationError(rejected)",
      "requested dataset version does not match",
      "requested predictor manifest does not match",
      '"sample_limit": int(request.sample_limit)',
      "json.dumps(cache_payload, sort_keys=True",
      "hashlib.sha256",
      "sample_limit = min(int(request.sample_limit), eligible_rows)",
      "deterministic_proportional_stratified",
      '"maximum_rows": 5000',
      '"scope": "rendered_sample"',
      '"population_rows"',
      '"eligible_rows"',
      '"returned_rows"',
      '"pair_metrics"',
      '"n": int(len(pairs))',
      '"target_source_excluded"',
    ],
    "Relationship sample service",
  );
  const pointSerialization = sourceBetween(
    relationshipService,
    "point: dict[str, Any] = {",
    "points.append(point)",
    "Relationship point serialization",
  );
  assertIncludes(
    pointSerialization,
    [
      '"x":',
      '"y":',
      '"z":',
      '"size":',
      '"target_group":',
      '"segment_group":',
      '"selection_value":',
    ],
    "Relationship point serialization",
  );
  assert.doesNotMatch(
    pointSerialization,
    /["']target["']\s*:/,
    "Raw target values must never be serialized into plot points.",
  );
});

check("Backend returns pairwise N and strips the raw target from bounded pairwise data", () => {
  const relationshipsService = sourceBetween(
    workspaceService,
    "    def _relationships(",
    "    def _prepare_vif_frame(",
    "Relationships service",
  );
  assertIncludes(
    relationshipsService,
    [
      "correlation_n_matrix",
      "numeric_df[left].notna() & numeric_df[right].notna()",
      '"correlation_n_matrix": correlation_n_matrix',
      "RelationshipSampleValidationError(rejected_pairwise)",
      'rendered.drop(columns=["__target__"], errors="ignore")',
      '"pairwise_sample"',
    ],
    "Relationships service",
  );
});

check("Code-context fingerprint compares governed identity without path leakage", () => {
  assert.ok(
    codeSafety.includes(`CODE_CONTEXT_WARNING = "${STALE_CODE_WARNING}"`),
    "The stale-code warning must be exact.",
  );
  const fingerprint = sourceBetween(
    codeSafety,
    "export type CodeContextFingerprint = {",
    "};",
    "Code-context fingerprint",
  );
  assertIncludes(
    fingerprint,
    [
      "datasetId: string",
      "datasetVersion: string",
      "datasetName: string",
      "target: string",
      "predictorManifestId: string",
      "workflowPage: string",
      "language: CodeContextLanguage",
      "generatedAt: string",
    ],
    "Code-context fingerprint",
  );
  const identity = sourceBetween(
    codeSafety,
    "export function codeContextIdentity(",
    "function safeDisplayValue(",
    "Code-context identity",
  );
  assertIncludes(
    identity,
    [
      "context.datasetId",
      "context.datasetVersion",
      "context.datasetName",
      "context.target",
      "context.predictorManifestId",
      "context.workflowPage",
      "context.language",
    ],
    "Code-context identity",
  );
  assert.doesNotMatch(identity, /context\.generatedAt/);
  const displaySafety = sourceBetween(
    codeSafety,
    "function safeDisplayValue(",
    "const COMPARABLE_FIELDS",
    "Safe mismatch display",
  );
  assert.match(displaySafety, /leafName/);
  assert.match(displaySafety, /\[\\\\\/\]/);
});

check("Exact-pair acknowledgement gates persistence and preserves historical drafts", () => {
  const evaluation = sourceBetween(
    codeSafety,
    "export function evaluateCodeDraftContext(",
    "function emptyStore(",
    "Code-context evaluation",
  );
  assertIncludes(
    evaluation,
    [
      "requiresAcknowledgement",
      "codeDraftIdentity(draft, code)",
      "codeContextIdentity(currentContext)",
      "canUseAsCurrent: !requiresAcknowledgement || acknowledged",
      "warning: requiresAcknowledgement ? CODE_CONTEXT_WARNING : null",
    ],
    "Code-context evaluation",
  );
  const persistence = sourceBetween(
    codeSafety,
    "export function persistCodeDraft(",
    "export function acknowledgeCodeDraftContext(",
    "Code draft persistence",
  );
  assert.match(persistence, /if \(!evaluation\.canUseAsCurrent\) return \{ ok: false, evaluation \}/);
  const acknowledgement = sourceBetween(
    codeSafety,
    "export function acknowledgeCodeDraftContext(",
    "export function retainHistoricalCodeDraft(",
    "Code draft acknowledgement",
  );
  assertIncludes(
    acknowledgement,
    [
      "draftIdentity: codeDraftIdentity(working, code)",
      "currentContextIdentity: codeContextIdentity(currentContext)",
      "acknowledgedAt: isoNow()",
    ],
    "Code draft acknowledgement",
  );
  const retention = sourceBetween(
    codeSafety,
    "export function retainHistoricalCodeDraft(",
    "export function resetCodeDraftForCurrentContext(",
    "Historical draft retention",
  );
  assert.match(retention, /acknowledgement: undefined/);
  const reset = sourceBetween(
    codeSafety,
    "export function resetCodeDraftForCurrentContext(",
    "export function codeContextSummary(",
    "Code draft reset",
  );
  assertIncludes(
    reset,
    [
      "archivedAt: timestamp",
      "historicalCode",
      "origin: \"generated_reset\"",
      "drafts: [...drafts, draft]",
    ],
    "Code draft reset",
  );
});

check("CLASS_TRAIN to HELOC_TRAIN is blocked for both Python and SAS until acknowledged", () => {
  class MemoryStorage {
    values = new Map();

    getItem(key) {
      return this.values.has(String(key)) ? this.values.get(String(key)) : null;
    }

    setItem(key, value) {
      this.values.set(String(key), String(value));
    }

    removeItem(key) {
      this.values.delete(String(key));
    }
  }

  const localStorage = new MemoryStorage();
  const sessionStorage = new MemoryStorage();
  let activeDataset = {
    headers: ["V1", "V2", "Amount", "Class"],
    rows: [{ V1: 0.1, V2: -0.2, Amount: 42, Class: 0 }],
    target: "Class",
    selected_columns: ["V1", "V2", "Amount"],
    dataset_library: {
      datasetId: "ds-class",
      versionId: "class-v1",
      datasetName: "C:\\sensitive\\CLASS_TRAIN.csv",
    },
  };
  const compiled = ts.transpileModule(codeSafety, {
    compilerOptions: {
      target: ts.ScriptTarget.ES2021,
      module: ts.ModuleKind.CommonJS,
      esModuleInterop: true,
    },
    fileName: "codeContextSafety.ts",
  }).outputText;
  const moduleRecord = { exports: {} };
  const sandbox = {
    module: moduleRecord,
    exports: moduleRecord.exports,
    require(specifier) {
      if (specifier === "./activeProjectContext") {
        return { getCachedProjectId: () => "project-phase-11" };
      }
      if (specifier === "./authSession") {
        return { getCachedUserId: () => "user-phase-11" };
      }
      if (specifier === "./localDataset") {
        return {
          loadLocalDataset: () => activeDataset,
          localDatasetVersion: (dataset) =>
            `${dataset?.dataset_library?.versionId}|${dataset?.target}|${(
              dataset?.selected_columns ?? []
            ).join(",")}`,
        };
      }
      throw new Error(`Unexpected code-context test import: ${specifier}`);
    },
    localStorage,
    sessionStorage,
    window: { dispatchEvent() {} },
    CustomEvent: class CustomEvent {
      constructor(type) {
        this.type = type;
      }
    },
    crypto: webcrypto,
    console,
    Date,
    JSON,
    Math,
    encodeURIComponent,
  };
  vm.runInNewContext(compiled, sandbox, {
    filename: "codeContextSafety.phase11.js",
  });
  const safety = moduleRecord.exports;
  const contexts = {};
  for (const language of ["python", "sas"]) {
    const scope = {
      userId: "user-phase-11",
      projectId: "project-phase-11",
      workflowPage: "/step02",
      language,
    };
    const currentContext = safety.buildCurrentCodeContext({
      workflowPage: "/step02",
      language,
      projectId: "project-phase-11",
      dataset: activeDataset,
      generatedAt: "2026-07-27T10:00:00.000Z",
    });
    const code =
      language === "python"
        ? "df[['V1', 'V2', 'Amount', 'Class']]"
        : "proc freq data=work.CLASS_TRAIN; tables Class; run;";
    assert.equal(
      safety.persistCodeDraft({ scope, currentContext, code }).ok,
      true,
    );
    contexts[language] = { scope, code };
  }

  activeDataset = {
    headers: ["ExternalRiskEstimate", "RiskPerformance", "bad_flag"],
    rows: [
      {
        ExternalRiskEstimate: 72,
        RiskPerformance: "Good",
        bad_flag: 0,
      },
    ],
    target: "bad_flag",
    selected_columns: ["ExternalRiskEstimate"],
    dataset_library: {
      datasetId: "ds-heloc",
      versionId: "heloc-v2",
      datasetName: "D:\\governed\\HELOC_TRAIN.csv",
    },
  };

  for (const language of ["python", "sas"]) {
    const { scope, code } = contexts[language];
    const currentContext = safety.buildCurrentCodeContext({
      workflowPage: "/step02",
      language,
      projectId: "project-phase-11",
      dataset: activeDataset,
    });
    const historical = safety.loadCodeDraft({ scope }).draft;
    const mismatch = safety.evaluateCodeDraftContext(
      historical,
      currentContext,
      code,
    );
    assert.equal(mismatch.warning, STALE_CODE_WARNING);
    assert.equal(mismatch.canUseAsCurrent, false);
    assert.ok(mismatch.details.some((detail) => detail.field === "datasetId"));
    assert.ok(mismatch.details.some((detail) => detail.field === "target"));
    assert.ok(
      mismatch.details.every(
        (detail) =>
          !detail.draftValue.includes("C:\\") &&
          !detail.currentValue.includes("D:\\"),
      ),
      "Mismatch details must not expose source paths.",
    );
    assert.equal(
      safety.persistCodeDraft({ scope, currentContext, code }).ok,
      false,
      `${language} stale code must not save as current evidence.`,
    );
  }

  const python = contexts.python;
  const helocPythonContext = safety.buildCurrentCodeContext({
    workflowPage: "/step02",
    language: "python",
    projectId: "project-phase-11",
    dataset: activeDataset,
  });
  const acknowledged = safety.acknowledgeCodeDraftContext({
    scope: python.scope,
    currentContext: helocPythonContext,
    code: python.code,
  });
  assert.equal(
    safety.evaluateCodeDraftContext(
      acknowledged,
      helocPythonContext,
      python.code,
    ).canUseAsCurrent,
    true,
  );
  assert.equal(
    safety.evaluateCodeDraftContext(
      acknowledged,
      helocPythonContext,
      `${python.code}\n# changed`,
    ).canUseAsCurrent,
    false,
    "Editing must invalidate the exact-pair acknowledgement.",
  );
  const reset = safety.resetCodeDraftForCurrentContext({
    scope: contexts.sas.scope,
    currentContext: safety.buildCurrentCodeContext({
      workflowPage: "/step02",
      language: "sas",
      projectId: "project-phase-11",
      dataset: activeDataset,
    }),
    generatedCode: "proc contents data=work.HELOC_TRAIN; run;",
    historicalCode: contexts.sas.code,
  });
  assert.equal(reset.archivedDraft.code, contexts.sas.code);
  assert.ok(reset.archivedDraft.archivedAt);
  assert.equal(reset.draft.context.datasetId, "ds-heloc");
});

check("Python and SAS UI actions gate save, execution, and historical copies", () => {
  assertIncludes(
    codeWorkspace,
    [
      "current.contextSafety.warning",
      "Historical: {detail.draftValue}",
      "Current: {detail.currentValue}",
      "Keep historical draft",
      "Reset to current generated code",
      "View diff",
      "Save as separate notebook version (copy)",
      "Acknowledge exact context pair",
      "Editing the code invalidates the",
    ],
    "Code workspace context warning",
  );
  assertIncludes(
    pythonPanel,
    [
      "pythonContextEvaluation.canUseAsCurrent",
      "sasContextEvaluation.canUseAsCurrent",
      'if (!persist("python")) return',
      'if (!persist("sas")) return',
      'canSave: pythonContextEvaluation.canUseAsCurrent',
      'canSave: sasContextEvaluation.canUseAsCurrent',
      "retainHistoricalCodeDraft",
      "resetCodeDraftForCurrentContext",
      "acknowledgeCodeDraftContext",
      "saveHistoricalNotebookCopy",
      "It is not current workflow evidence",
    ],
    "Python/SAS context gates",
  );
});

check("Notebook export omits unacknowledged stale code and labels acknowledged history", () => {
  assertIncludes(
    notebookExport,
    [
      "Historical User-Edited Python Code Omitted",
      "Historical User-Edited SAS Code Omitted",
      "Acknowledged Historical User-Edited Python Code",
      "Acknowledged Historical User-Edited SAS Code",
      "!pythonDraft.evaluation.canUseAsCurrent",
      "!sasDraft.evaluation.canUseAsCurrent",
      "pythonDraft.evaluation.acknowledged",
      "sasDraft.evaluation.acknowledged",
      "The historical source was intentionally omitted.",
      "The historical SAS source was intentionally omitted.",
      "exact draft/current-context acknowledgement",
    ],
    "Notebook evidence safety",
  );
});

if (failures.length) {
  console.error(
    `\nedaVisualIntelligencePhase11.test.mjs: ${failures.length} of ${checkCount} checks failed.`,
  );
  failures.forEach(({ name, error }, index) => {
    console.error(`\n${index + 1}. ${name}`);
    console.error(error instanceof Error ? error.message : String(error));
  });
  process.exitCode = 1;
} else {
  console.log(
    `edaVisualIntelligencePhase11.test.mjs: all ${checkCount} checks passed.`,
  );
}
