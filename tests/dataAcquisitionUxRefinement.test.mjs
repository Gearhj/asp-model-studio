import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

const ROOT = new URL("../", import.meta.url);
const read = (path) =>
  readFileSync(new URL(path, ROOT), "utf8").replace(/\r\n/g, "\n");

const acquisition = read("src/steps/Step01_DataAcquisition.tsx");
const loadProgress = read(
  "src/components/dataAcquisition/DatasetLoadProgressPanel.tsx",
);
const sectionNav = read(
  "src/components/dataAcquisition/DataAcquisitionSectionNav.tsx",
);
const specialValues = read("src/components/BureauReviewPanel.tsx");
const codePanel = read("src/components/StepPythonPanel.tsx");
const reproducibility = read("src/lib/dataAcquisitionReproducibility.ts");

function sourceBetween(source, startMarker, endMarker, label) {
  const start = source.indexOf(startMarker);
  const end = source.indexOf(endMarker, start + startMarker.length);
  assert.notEqual(start, -1, `Missing ${label} start marker.`);
  assert.ok(end > start, `Missing ${label} end marker.`);
  return source.slice(start, end);
}

function occurrences(source, value) {
  return source.split(value).length - 1;
}

test("one canonical Data Contract replaces repeated dataset summaries", () => {
  assert.equal(
    occurrences(acquisition, '<StepShell\n      title="Data Acquisition"'),
    1,
    "Data Acquisition should have one canonical workflow hero.",
  );
  assert.match(
    acquisition,
    /eyebrow="Predictive Modeling[^\n]*Data Contract"/,
  );
  assert.match(acquisition, /data-testid="data-contract-status-chips"/);
  assert.match(acquisition, /data-testid="data-acquisition-scope-strip"/);
  assert.doesNotMatch(acquisition, /Current Dataset Summary/);
  assert.doesNotMatch(acquisition, /CurrentDatasetSummary/);
  assert.doesNotMatch(acquisition, /ReadinessSummary/);

  const hero = sourceBetween(
    acquisition,
    "heroMetrics={[",
    "] satisfies AtlasWorkflowMetric[]}",
    "canonical Data Contract metrics",
  );
  for (const label of [
    "Dataset",
    "Exact Version",
    "Eligible Population",
    "Source Columns",
    "Target",
    "Authorized Predictors",
    "Analysis Partition",
  ]) {
    assert.ok(hero.includes(`label: "${label}"`), `Missing hero metric: ${label}`);
  }
  assert.match(
    hero,
    /governedPredictorAuthorization\.funnel\.authorized_predictor_count/,
    "The canonical predictor count must come from backend authorization.",
  );
  assert.doesNotMatch(
    hero,
    /selected\.length|headers\.length/,
    "The canonical Data Contract must not infer governed counts from browser state.",
  );
});

test("successful load details are collapsed but natively keyboard-accessible", () => {
  const completed = sourceBetween(
    loadProgress,
    'if (progress.phase === "loaded")',
    "  return (\n    <div",
    "completed load branch",
  );
  assert.match(completed, /<details[\s\S]*data-load-phase=\{progress\.phase\}/);
  const openingDetailsTag = completed.slice(
    completed.indexOf("<details"),
    completed.indexOf(">", completed.indexOf("<details")) + 1,
  );
  assert.doesNotMatch(
    openingDetailsTag,
    /\sopen(?:\s|=|>)/,
    "Completed details should be collapsed by default.",
  );
  assert.match(completed, /<summary[^>]*className="[^"]*cursor-pointer/);
  assert.match(completed, /focus-visible:outline/);
  assert.match(completed, /Dataset loaded and verified/);
  assert.match(
    completed,
    /\{summary\.completed\} of \{summary\.total\} checks completed/,
  );
  assert.match(completed, /View load details/);
  assert.match(completed, /data-testid="dataset-load-completed-details"/);
  assert.match(completed, /DATASET_LOAD_STAGES\.map/);
});

test("the sticky six-section navigator exposes active, keyboard, and unresolved state", () => {
  const navItems = sourceBetween(
    acquisition,
    "const sectionNavItems = useMemo<DataAcquisitionSectionNavItem[]>",
    "\n\n  return (",
    "Data Acquisition section navigation model",
  );
  const ids = [
    "source-target",
    "data-quality-readiness",
    "credit-bureau-review",
    "predictor-authorization",
    "analysis-partition-readiness",
    "code-lineage",
  ];
  assert.equal(
    occurrences(navItems, "id: "),
    6,
    "The page should expose exactly six primary sections.",
  );
  for (const id of ids) {
    assert.ok(navItems.includes(`id: "${id}"`), `Missing section nav target: ${id}`);
    assert.ok(
      `${acquisition}\n${specialValues}`.includes(`id="${id}"`),
      `Section nav target is not present in the page: ${id}`,
    );
  }
  assert.match(navItems, /unresolvedCount: bureauReviewStatus\?\.unresolvedRequirements/);

  assert.match(sectionNav, /className="sticky top-3 z-30/);
  assert.match(sectionNav, /aria-label="Data Acquisition sections"/);
  assert.match(sectionNav, /<button[\s\S]*type="button"/);
  assert.match(sectionNav, /focus-visible:outline/);
  assert.match(sectionNav, /aria-current=\{active \? "location" : undefined\}/);
  assert.match(sectionNav, /IntersectionObserver/);
  assert.match(sectionNav, /setActiveId\(next\)/);
  assert.match(sectionNav, /scrollIntoView\(\{ behavior: "smooth", block: "start" \}\)/);
  assert.match(sectionNav, /item\.unresolvedCount[\s\S]*unresolved/);
  assert.match(sectionNav, /data-section-state=\{item\.state\}/);
});

test("preview and quality sections retain unique information instead of identity summaries", () => {
  const preview = sourceBetween(
    acquisition,
    "function DataPreview(",
    "\nfunction DataQualityPanel(",
    "Data Preview component",
  );
  assert.match(preview, /data-testid="browser-preview-scope-note"/);
  assert.match(
    preview,
    /hasGovernedPopulation/,
  );
  assert.match(preview, /Preview limits do not change backend modeling scope/);
  assert.match(
    preview,
    /current unregistered workspace[\s\S]*Backend modeling scope is not governed until registration and exact-version activation succeed/,
    "A browser-only upload must never be labelled as a governed population.",
  );
  assert.match(
    acquisition,
    /governedPopulationRowCount=\{backendRowCount\}/,
    "The governed preview denominator must come from backend authority.",
  );
  assert.doesNotMatch(
    acquisition,
    /selectedDataset\.latestVersion\?\.rowCount|<Stat label="Library Dataset"/,
    "The selected-version workspace must not repeat a latest-version asset summary.",
  );
  assert.doesNotMatch(preview, /SummaryDatum|Current Dataset|Dataset Version|Selected Predictors|Source Type/);

  const quality = sourceBetween(
    acquisition,
    "function DataQualityPanel(",
    "\nfunction QualityGroup(",
    "Data Quality component",
  );
  for (const uniqueGroup of [
    "Row and column health",
    "Missingness and duplicates",
    "Predictor readiness",
    "Leakage screening",
  ]) {
    assert.equal(
      occurrences(quality, `title="${uniqueGroup}"`),
      1,
      `Quality group should appear once: ${uniqueGroup}`,
    );
  }
  assert.doesNotMatch(
    quality,
    /Dataset identity and scope|Dataset Version|Modeling Rows|Browser Preview Rows|Target column|Event rate/i,
  );
  assert.match(
    acquisition,
    /Review unique structural findings without repeating the governed dataset identity\./,
  );
});

test("predictor funnel is backend-authoritative and names exclusions and scope limits", () => {
  const funnel = sourceBetween(
    acquisition,
    "function PredictorAuthorizationFunnel(",
    "\nfunction UploadPanel(",
    "Predictor Authorization Funnel",
  );
  assert.match(funnel, /Backend-authoritative Predictor Authorization Funnel/);
  for (const backendCount of [
    "funnel.source_column_count",
    "funnel.candidate_predictor_count",
    "funnel.selected_predictor_count",
    "funnel.authorized_predictor_count",
  ]) {
    assert.ok(funnel.includes(backendCount), `Missing backend count: ${backendCount}`);
  }
  assert.doesNotMatch(funnel, /headers\.length|selected\.length/);
  assert.match(funnel, /Browser selections cannot replace this exact governed contract/);
  assert.match(funnel, /label: "Model-ready predictors"/);
  assert.match(funnel, /value: "Not established here"/);
  assert.match(funnel, /note: "Established by training preflight"/);
  assert.match(funnel, /funnel\.target_exclusions\.length/);
  assert.match(funnel, /authorization\.deterministic_source_exclusions/);
  assert.match(funnel, /authorization\.excluded_fields\[field\]/);
  assert.match(funnel, /funnel\.additional_exclusions/);

  const funnelUse = sourceBetween(
    acquisition,
    "<PredictorAuthorizationFunnel",
    "/>",
    "Predictor Authorization Funnel usage",
  );
  assert.match(funnelUse, /authorization=\{governedPredictorAuthorization\}/);
  assert.match(funnelUse, /governedProfile\.profile \? predictorCounts\.evaluated : null/);
  assert.match(funnelUse, /unavailable=\{predictorCounts\.unavailable\}/);
  assert.match(
    acquisition,
    /selectedPredictorCount:\s*reproducibilityContext\?\.predictor_authorization\?\.funnel\s*\.authorized_predictor_count \?\? 0/,
    "The lifecycle gate must use the exact backend authorization count.",
  );
  assert.doesNotMatch(
    acquisition,
    /selectedPredictorCount:\s*selected\.length/,
    "A stale browser selection count must not override the backend contract.",
  );

  assert.match(
    reproducibility,
    /model_ready_status: "not_established_in_data_acquisition"/,
  );
  assert.match(reproducibility, /target_exclusions: Array<\{ field: string; reason: string \}>/);
  assert.match(reproducibility, /deterministic_source_exclusions: string\[\]/);
});

test("exact code context is colocated under Code and Lineage and stale context is withheld", () => {
  assert.match(acquisition, /showDeveloperTools=\{false\}/);
  const codeAndLineage = sourceBetween(
    acquisition,
    '<section id="code-lineage"',
    "\n        )}\n      </div>",
    "Code and Lineage section",
  );
  assert.match(codeAndLineage, /<h2[^>]*>Code &amp; Lineage<\/h2>/);
  assert.match(codeAndLineage, /<LineagePanel[^>]*\/>[\s\S]*<StepPythonPanel \/>/);
  assert.equal(
    occurrences(acquisition, "<StepPythonPanel />"),
    1,
    "The exact code panel should render once, inside Code and Lineage.",
  );

  assert.match(
    reproducibility,
    /window\.dispatchEvent\(new CustomEvent\(REPRODUCIBILITY_CONTEXT_PENDING_EVENT\)\)/,
  );
  assert.match(
    reproducibility,
    /window\.dispatchEvent\(new CustomEvent\(REPRODUCIBILITY_CONTEXT_CONFIRMED_EVENT\)\)/,
  );
  const pendingHandler = sourceBetween(
    acquisition,
    "    const markPending = () => {",
    "    const refreshConfirmed = () => {",
    "reproducibility pending handler",
  );
  assert.match(pendingHandler, /localDraftPending = true/);
  assert.match(pendingHandler, /setReproducibilityContextPhase\("pending"\)/);
  assert.doesNotMatch(
    pendingHandler,
    /setReproducibilityContext\(null\)|requestRevision\s*\+=|controller\.abort/,
    "A local predictor draft must not discard or cancel an in-flight exact governed baseline.",
  );
  assert.match(acquisition, /window\.addEventListener\([\s\S]*REPRODUCIBILITY_CONTEXT_PENDING_EVENT,[\s\S]*markPending/);
  assert.match(acquisition, /window\.addEventListener\([\s\S]*REPRODUCIBILITY_CONTEXT_CONFIRMED_EVENT,[\s\S]*refreshConfirmed/);
  assert.match(codePanel, /REPRODUCIBILITY_CONTEXT_PENDING_EVENT[\s\S]*markPending/);
  assert.match(codePanel, /REPRODUCIBILITY_CONTEXT_CONFIRMED_EVENT[\s\S]*refreshConfirmed/);

  const targetPersistence = sourceBetween(
    acquisition,
    'const backendRes = await fetch(`${BASE}/data/set_target`',
    "    if (backendSynced && localSaveStatus",
    "target persistence confirmation",
  );
  const contractGuard = targetPersistence.indexOf(
    "if (!targetContractId || !predictorAuthorizationId)",
  );
  const confirmed = targetPersistence.indexOf(
    "notifyReproducibilityContextConfirmed()",
  );
  assert.ok(contractGuard >= 0 && confirmed > contractGuard);
  assert.match(acquisition, /markReproducibilityContextPending\(\);[\s\S]{0,120}setKept\(nextKept\)/);
});

test("split-ratio changes use an explicit governed backend preview", () => {
  assert.match(
    acquisition,
    /data-testid="open-analysis-partition-reset"[\s\S]*Change Split Ratio [^\r\n<]* Creates New Revision[\s\S]*<\/Link>/,
  );
  const resetWorkspace = sourceBetween(
    acquisition,
    "function AnalysisPartitionResetWorkspace(",
    "\nfunction SummaryDatum(",
    "governed split-ratio workspace",
  );
  assert.match(resetWorkspace, /Governed split-ratio change/);
  assert.match(resetWorkspace, /Backend-authoritative preview/);
  assert.match(resetWorkspace, /data-testid="analysis-partition-reset-preview"/);
  assert.match(resetWorkspace, /props\.preview\.developmentRows/);
  assert.match(resetWorkspace, /props\.preview\.holdoutRows/);
  assert.match(resetWorkspace, /props\.preview\.blockers/);
  assert.match(resetWorkspace, /Boolean\(props\.preview\.previewFingerprint\)/);
  assert.match(resetWorkspace, /Fixed random seed/);
  assert.match(resetWorkspace, /Fixed stratification/);

  const previewEffect = sourceBetween(
    acquisition,
    "const resetPreviewReady =",
    "\n  useEffect(() => {\n    if (!analysisPartitionResetMode)",
    "analysis partition preview effect",
  );
  assert.match(previewEffect, /analysisPartitionResetMode/);
  assert.match(previewEffect, /analysisPartitionResetHoldoutShare/);
  assert.match(previewEffect, /readAnalysisPartitionPreview\(/);
  assert.match(previewEffect, /setAnalysisPartitionPreview\(preview\)/);
});

test("special-value review is visually prominent, discoverable, and blocking when unresolved", () => {
  assert.match(specialValues, /<section id="credit-bureau-review"/);
  assert.match(specialValues, /data-testid="special-value-decision-workspace"/);
  assert.match(specialValues, /from-slate-950 via-indigo-950 to-indigo-900/);
  assert.match(specialValues, /Special-Value Treatment Review/);
  assert.match(specialValues, /data-testid="special-value-feature-table"/);
  assert.match(specialValues, /data-testid="special-value-feature-row"/);
  assert.match(specialValues, /aria-label=\{`Selected treatment for \$\{variable\.variable\}`\}/);
  assert.match(specialValues, /Apply selected default to unresolved attributes/);
  assert.match(specialValues, /data-testid="confirmed-special-value-summary"/);
  assert.match(specialValues, /Confirm Special-Value Treatment/);
  assert.match(
    specialValues,
    /disabled=\{\s*!result \|\|\s*!durableReview \|\|\s*saving \|\|\s*draftUnresolvedCount > 0\s*\}/,
  );
  assert.match(specialValues, /const reviewedCount = durableReview\?\.reviewed_count \?\? 0/);
  assert.match(specialValues, /const unresolvedCount = durableReview\?\.open_count \?\? likelyVariables\.length/);
  assert.match(specialValues, /browser draft has unsaved changes and is not authoritative/);
  assert.match(specialValues, /durableReview\.blocks_continuation/);
  assert.match(specialValues, /onReviewStatus\?\.\(\{[\s\S]*unresolvedRequirements:[\s\S]*blocking:/);

  const callout = sourceBetween(
    acquisition,
    "{bureauReviewStatus?.blocking &&",
    "        ) : null}",
    "special-value attention callout",
  );
  assert.match(callout, /!bureauReviewStatus\.loading/);
  assert.match(callout, /!bureauReviewStatus\.error/);
  assert.match(callout, /data-testid="special-value-attention-callout"/);
  assert.match(callout, /Special-value review requires attention/);
  assert.match(callout, /Go to Special-Value Review/);
  assert.match(callout, /getElementById\("credit-bureau-review"\)[\s\S]*scrollIntoView/);

  const continuationGate = sourceBetween(
    acquisition,
    "const specialValueReviewExpected = Boolean(",
    "    if (analysisPartitionIsCurrent)",
    "special-value continuation gate",
  );
  assert.match(continuationGate, /bureauReviewStatus\.loading \|\| bureauReviewStatus\.blocking/);
  assert.match(continuationGate, /canContinue: false/);
  assert.match(continuationGate, /Special-value review required/);
  assert.match(continuationGate, /Complete Special-Value Review to Continue/);
  assert.match(continuationGate, /Confirm the governed Special-Value Treatment Review before continuing/);
});
