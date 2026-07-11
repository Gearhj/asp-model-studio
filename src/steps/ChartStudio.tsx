import type React from "react";
import { useEffect, useMemo, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { BarChart3, Code2, Copy, Database, Download, FileSpreadsheet, GitBranch, Play, RotateCcw, Save, Sparkles } from "lucide-react";
import BrandLogo from "../components/BrandLogo";
import { getDataset, getDatasetPreview, getDatasetProfile, listDatasets, type DatasetPreview, type DatasetProfile, type DatasetSummary, type DatasetVersionSummary } from "../lib/datasetLibrary";
import { exportChartDataExcel, listChartInsights, saveChartInsight, type ChartStudioRoleAssignments } from "../lib/chartStudio";
import { exportAnalyticsResultExcel, runAnalyticsPreviewSql, saveAnalyticsInsight, type AtlasAnalyticsInsight } from "../lib/analyticsWorkbench";
import { runUserPython, runUserR, runUserSasCompatible, type CodeRunResult } from "../lib/codeExecution";
import { CodeExecutionResult } from "../components/code/CodeExecutionResult";
import { useWorkflowStore } from "../state/useWorkflowStore";
import { isScoredOutputDataset } from "../lib/modelDiagnostics";

type DatasetDetail = DatasetSummary & { versions?: DatasetVersionSummary[] };
type ChartRow = Record<string, unknown>;
type ChartTypeId =
  | "bar"
  | "horizontal_bar"
  | "stacked_bar"
  | "line"
  | "step"
  | "scatter"
  | "histogram"
  | "density"
  | "box"
  | "grouped_bar"
  | "grouped_box"
  | "grouped_scatter"
  | "grouped_line"
  | "heatmap"
  | "correlation_heatmap"
  | "pareto"
  | "waterfall"
  | "control"
  | "dual_axis"
  | "lift_decile"
  | "residual_diagnostic"
  | "forecast"
  | "survival"
  | "means"
  | "data_profile"
  | "sankey"
  | "network"
  | "scatter_matrix"
  | "correlation_matrix"
  | "pair_plot"
  | "data_profile_matrix"
  | "panel_category"
  | "panel_time"
  | "small_multiples"
  | "comparison_panels"
  | "custom"
  | "custom_roles"
  | "saved_template";

type GalleryTab = "Basic" | "Grouped" | "Analytical" | "Matrix" | "Panels" | "Custom";
type BinningMethod = "quantile" | "equal_width";
type BinningConfig = { enabled: boolean; bins: number; method: BinningMethod };
type CodeTab = "Python" | "SQL" | "R" | "SAS-compatible";

const BINNED_ROLE_PREFIX = "__atlas_binned__:";

const CHART_FAMILIES: Array<{
  family: GalleryTab;
  charts: Array<{ id: ChartTypeId; label: string; description: string; bestFor: string; implemented: boolean }>;
}> = [
  {
    family: "Basic",
    charts: [
      { id: "scatter", label: "Scatter Plot", description: "Inspect numeric relationships and outliers.", bestFor: "relationships, clusters, outliers", implemented: true },
      { id: "line", label: "Line Plot", description: "Show a measure across ordered values or time.", bestFor: "trends and ordered measures", implemented: true },
      { id: "step", label: "Step Plot", description: "Show discrete changes across ordered values.", bestFor: "threshold and staged changes", implemented: true },
      { id: "histogram", label: "Histogram", description: "Review distribution shape for a numeric variable.", bestFor: "distribution shape", implemented: true },
      { id: "box", label: "Box Plot", description: "Compare numeric distributions by group.", bestFor: "spread, outliers, group comparison", implemented: true },
      { id: "bar", label: "Bar Chart", description: "Compare an aggregated measure across categories.", bestFor: "category comparison", implemented: true },
      { id: "horizontal_bar", label: "Horizontal Bar Chart", description: "Compare categories with long labels.", bestFor: "ranked category labels", implemented: true },
      { id: "density", label: "Density Plot", description: "Estimate a smooth distribution curve.", bestFor: "distribution comparison", implemented: true },
    ],
  },
  {
    family: "Grouped",
    charts: [
      { id: "grouped_bar", label: "Grouped Bar", description: "Compare grouped categories side by side.", bestFor: "category-by-segment comparison", implemented: true },
      { id: "stacked_bar", label: "Stacked Bar", description: "Compare totals and composition.", bestFor: "composition and totals", implemented: true },
      { id: "grouped_box", label: "Grouped Box Plot", description: "Compare distributions across grouped segments.", bestFor: "spread by segment", implemented: true },
      { id: "grouped_scatter", label: "Grouped Scatter", description: "Inspect numeric relationships by group.", bestFor: "segmented relationships", implemented: true },
      { id: "grouped_line", label: "Grouped Line", description: "Compare multiple trend lines.", bestFor: "multi-series trends", implemented: true },
    ],
  },
  {
    family: "Analytical",
    charts: [
      { id: "correlation_heatmap", label: "Correlation Heatmap", description: "Compare numeric pairwise relationships.", bestFor: "relationship screening", implemented: true },
      { id: "heatmap", label: "Heatmap", description: "Show a measure across two categorical or binned axes.", bestFor: "matrix-style segment intensity", implemented: true },
      { id: "pareto", label: "Pareto", description: "Rank categories and cumulative contribution.", bestFor: "concentration and top drivers", implemented: true },
      { id: "waterfall", label: "Waterfall", description: "Show cumulative positive and negative changes.", bestFor: "bridge and variance analysis", implemented: true },
      { id: "control", label: "Control Chart", description: "Detect process shifts against control limits.", bestFor: "process stability", implemented: true },
      { id: "dual_axis", label: "Dual Axis", description: "Compare two measures over the same x axis.", bestFor: "related measures with different scales", implemented: true },
      { id: "sankey", label: "Sankey", description: "Summarize source-to-target flows.", bestFor: "flows and transitions", implemented: true },
      { id: "residual_diagnostic", label: "Residual Diagnostics", description: "Inspect residual patterns for regression.", bestFor: "model error diagnostics", implemented: true },
      { id: "lift_decile", label: "Lift / Decile", description: "Evaluate model lift by ranked groups.", bestFor: "model performance by rank", implemented: true },
      { id: "forecast", label: "Forecast", description: "Show projected values with uncertainty.", bestFor: "time-aware prediction", implemented: true },
      { id: "survival", label: "Survival", description: "Show survival or retention curves.", bestFor: "time-to-event analysis", implemented: true },
      { id: "means", label: "Means Plot", description: "Compare means and uncertainty by group.", bestFor: "statistical group comparison", implemented: true },
      { id: "data_profile", label: "Data Profile", description: "Summarize variable quality and distribution.", bestFor: "EDA overview", implemented: true },
    ],
  },
  {
    family: "Matrix",
    charts: [
      { id: "scatter_matrix", label: "Scatter Matrix", description: "Compare multiple numeric relationships.", bestFor: "multi-variable screening", implemented: true },
      { id: "correlation_matrix", label: "Correlation Matrix", description: "Show pairwise correlations as a matrix.", bestFor: "relationship screening", implemented: true },
      { id: "pair_plot", label: "Pair Plot", description: "Inspect distributions and pairwise scatter.", bestFor: "EDA diagnostics", implemented: true },
      { id: "data_profile_matrix", label: "Data Profile Matrix", description: "Review data quality across columns.", bestFor: "data profiling", implemented: true },
    ],
  },
  {
    family: "Panels",
    charts: [
      { id: "panel_category", label: "Panel by Category", description: "Repeat a chart by category.", bestFor: "small-multiple comparison", implemented: true },
      { id: "panel_time", label: "Panel by Time", description: "Repeat a chart across time windows.", bestFor: "period comparison", implemented: true },
      { id: "small_multiples", label: "Small Multiples", description: "Display many related charts together.", bestFor: "segment diagnostics", implemented: true },
      { id: "comparison_panels", label: "Comparison Panels", description: "Compare chart variants side by side.", bestFor: "decision review", implemented: true },
    ],
  },
  {
    family: "Custom",
    charts: [
      { id: "custom", label: "Custom Chart", description: "Start from a flexible chart template.", bestFor: "custom analytical views", implemented: false },
      { id: "custom_roles", label: "User-defined Role Mapping", description: "Define custom visual encodings.", bestFor: "advanced users", implemented: false },
      { id: "saved_template", label: "Saved Templates", description: "Reuse a governed chart configuration.", bestFor: "standardized reporting", implemented: false },
    ],
  },
];

const WORKING_CHARTS = CHART_FAMILIES.flatMap((family) => family.charts).filter((chart) => chart.implemented);

export default function ChartStudio() {
  const [searchParams] = useSearchParams();
  const projectId = useWorkflowStore((state) => state.projectId);
  const projectName = useWorkflowStore((state) => state.projectName);
  const [datasets, setDatasets] = useState<DatasetSummary[]>([]);
  const [primaryDatasetId, setPrimaryDatasetId] = useState(searchParams.get("datasetId") ?? "");
  const [primaryDataset, setPrimaryDataset] = useState<DatasetDetail | null>(null);
  const [primaryVersionId, setPrimaryVersionId] = useState("");
  const [secondaryDatasetId, setSecondaryDatasetId] = useState("");
  const [secondaryVersionId, setSecondaryVersionId] = useState("");
  const [joinKey, setJoinKey] = useState("");
  const [datasetTypeFilter, setDatasetTypeFilter] = useState<"all" | "scored_outputs">("all");
  const [profile, setProfile] = useState<DatasetProfile | null>(null);
  const [preview, setPreview] = useState<DatasetPreview>({ columns: [], rows: [] });
  const [chartType, setChartType] = useState<ChartTypeId>("bar");
  const [galleryTab, setGalleryTab] = useState<GalleryTab>("Basic");
  const [codeTab, setCodeTab] = useState<CodeTab>("Python");
  const [showDataTable, setShowDataTable] = useState(true);
  const [binning, setBinning] = useState<BinningConfig>({ enabled: true, bins: 5, method: "quantile" });
  const [businessQuestion, setBusinessQuestion] = useState("What pattern should this chart help validate?");
  const [roles, setRoles] = useState<ChartStudioRoleAssignments>({
    category: "",
    measure: "",
    aggregation: "sum",
    x: "",
    y: "",
    numeric: "",
    group: "",
    source: "",
    target: "",
    weight: "",
    bins: 10,
    topN: 10,
  });
  const [savedCharts, setSavedCharts] = useState<AtlasAnalyticsInsight[]>([]);
  const [userCode, setUserCode] = useState<Partial<Record<CodeTab, string>>>({});
  const [codeResults, setCodeResults] = useState<Partial<Record<CodeTab, CodeRunResult>>>({});
  const [runningCode, setRunningCode] = useState(false);
  const [status, setStatus] = useState("");
  const [error, setError] = useState("");

  useEffect(() => {
    listDatasets()
      .then((payload) => {
        setDatasets(payload.datasets);
        const first = payload.datasets[0];
        if (first) setPrimaryDatasetId((current) => current || first.datasetId);
      })
      .catch((err) => setError(err instanceof Error ? err.message : "ATLAS could not load Dataset Library assets."));
  }, []);

  useEffect(() => {
    if (!primaryDatasetId) return;
    let alive = true;
    setError("");
    getDataset(primaryDatasetId)
      .then((dataset) => {
        if (!alive) return;
        const versionId = dataset.versions?.[dataset.versions.length - 1]?.versionId || dataset.latestVersion?.versionId || "";
        setPrimaryDataset(dataset);
        setPrimaryVersionId((current) => current || versionId);
      })
      .catch((err) => setError(err instanceof Error ? err.message : "ATLAS could not load the selected dataset."));
    return () => {
      alive = false;
    };
  }, [primaryDatasetId]);

  useEffect(() => {
    if (!primaryDatasetId || !primaryVersionId) return;
    let alive = true;
    Promise.all([getDatasetProfile(primaryDatasetId, primaryVersionId), getDatasetPreview(primaryDatasetId, primaryVersionId), listChartInsights({ datasetId: primaryDatasetId })])
      .then(([profilePayload, previewPayload, insightsPayload]) => {
        if (!alive) return;
        setProfile(profilePayload.profile);
        setPreview(previewPayload);
        setSavedCharts(insightsPayload.insights);
      })
      .catch((err) => setError(err instanceof Error ? err.message : "ATLAS could not load chart preview context."));
    return () => {
      alive = false;
    };
  }, [primaryDatasetId, primaryVersionId]);

  const numericColumns = useMemo(() => inferNumericColumns(preview.rows, profile), [preview.rows, profile]);
  const categoricalColumns = useMemo(() => preview.columns.filter((column) => !numericColumns.includes(column)), [preview.columns, numericColumns]);
  const chartData = useMemo(() => computeChartData(chartType, preview.rows, roles, numericColumns, binning), [chartType, preview.rows, roles, numericColumns, binning]);
  const interpretation = useMemo(() => interpretChart(chartType, chartData, roles, primaryDataset?.name || "selected dataset"), [chartType, chartData, roles, primaryDataset?.name]);
  const generatedCode = useMemo(
    () => generateChartCode(chartType, primaryDataset?.name || "selected_dataset", primaryVersionId, roles, binning),
    [chartType, primaryDataset?.name, primaryVersionId, roles, binning]
  );

  useEffect(() => {
    setRoles((current) => defaultsForChart(chartType, current, numericColumns, categoricalColumns, preview.columns));
  }, [chartType, numericColumns.join("|"), categoricalColumns.join("|"), preview.columns.join("|")]);

  const selectedChart = CHART_FAMILIES.flatMap((family) => family.charts).find((chart) => chart.id === chartType);
  const primaryColumns = preview.columns;
  const activeGallery = CHART_FAMILIES.find((family) => family.family === galleryTab) ?? CHART_FAMILIES[0];
  const displayedDatasets = useMemo(() => datasetTypeFilter === "scored_outputs" ? datasets.filter(isScoredDataset) : datasets, [datasets, datasetTypeFilter]);
  const selectedDatasetIsScored = primaryDataset ? isScoredDataset(primaryDataset) : false;
  const editableCode = userCode[codeTab] ?? codeForTab(generatedCode, codeTab);
  const currentCodeResult = codeResults[codeTab] ?? null;

  useEffect(() => {
    if (displayedDatasets.length && !displayedDatasets.some((dataset) => dataset.datasetId === primaryDatasetId)) {
      setPrimaryDatasetId(displayedDatasets[0].datasetId);
      setPrimaryVersionId("");
    }
  }, [displayedDatasets, primaryDatasetId]);

  async function handleSaveInsight() {
    if (!primaryDatasetId || !primaryVersionId) {
      setError("Select a primary dataset and version before saving a chart insight.");
      return;
    }
    setError("");
    try {
      const insight = await saveChartInsight({
        title: `${selectedChart?.label || "Chart"} - ${primaryDataset?.name || primaryDatasetId}`,
        summary: interpretation,
        datasetId: primaryDatasetId,
        datasetName: primaryDataset?.name || primaryDatasetId,
        versionId: primaryVersionId,
        projectId,
        linkedProjectId: projectId,
        businessQuestion,
        chartType,
        roles,
        chartData,
        interpretation,
        generatedPython: generatedCode.python,
        generatedSql: generatedCode.sql,
        generatedR: generatedCode.r,
        generatedSas: generatedCode.sas,
        metadata: {
          projectName,
          secondaryDatasetId,
          secondaryVersionId,
          joinKey,
          previewRowCount: preview.rows.length,
          createdIn: "ATLAS Chart Studio",
        },
      });
      setSavedCharts((current) => [insight, ...current.filter((item) => item.insightId !== insight.insightId)]);
      setStatus("Chart insight saved.");
    } catch (err) {
      setError(err instanceof Error ? err.message : "ATLAS could not save this chart insight.");
    }
  }

  async function handleExcelExport() {
    setError("");
    try {
      const exported = await exportChartDataExcel({
        chartTitle: `${selectedChart?.label || "Chart"} - ${primaryDataset?.name || "Dataset"}`,
        chartType,
        datasetName: primaryDataset?.name || primaryDatasetId,
        datasetId: primaryDatasetId,
        versionId: primaryVersionId,
        businessQuestion,
        roles,
        chartData,
        interpretation,
        generatedPython: generatedCode.python,
        generatedSql: generatedCode.sql,
        generatedR: generatedCode.r,
        generatedSas: generatedCode.sas,
        metadata: { projectId, projectName, previewRows: preview.rows.length },
      });
      downloadBlob(exported.blob, exported.filename);
      setStatus("Chart data Excel export created.");
    } catch (err) {
      setError(err instanceof Error ? err.message : "ATLAS could not export chart data.");
    }
  }

  function codeContext() {
    return {
      preview_rows: preview.rows.slice(0, 500),
      previewRows: preview.rows.slice(0, 500),
      chartData: chartData.slice(0, 300),
      dataset_name: primaryDataset?.name || "selected_dataset",
      datasetName: primaryDataset?.name || "selected_dataset",
      version_id: primaryVersionId,
      versionId: primaryVersionId,
      chartType,
      roles,
      businessQuestion,
    };
  }

  async function handleRunCode() {
    setRunningCode(true);
    setError("");
    try {
      const context = codeContext();
      const code = editableCode;
      const result = codeTab === "Python"
        ? await runUserPython({
            code: runnablePython(code),
            projectId,
            workflowStep: "chart_studio",
            context,
          })
        : codeTab === "SQL"
          ? await runAnalyticsPreviewSql({
              sql: code,
              datasetName: primaryDataset?.name || "primary_dataset",
              versionId: primaryVersionId,
              previewRows: preview.rows.slice(0, 500) as Array<Record<string, unknown>>,
            })
          : codeTab === "R"
            ? await runUserR({ code, context })
            : await runUserSasCompatible({ code, context });
      setCodeResults((current) => ({ ...current, [codeTab]: result as CodeRunResult }));
      setStatus(`${codeTab} code execution completed.`);
    } catch (err) {
      setCodeResults((current) => ({
        ...current,
        [codeTab]: {
          ok: false,
          status: "error",
          stdout: "",
          stderr: err instanceof Error ? err.message : `${codeTab} execution failed.`,
          runtimeMs: 0,
        } as CodeRunResult,
      }));
    } finally {
      setRunningCode(false);
    }
  }

  async function handleSaveCodeSnippet() {
    setError("");
    try {
      const language = codeTab === "SAS-compatible" ? "sas" : codeTab.toLowerCase();
      const insight = await saveAnalyticsInsight({
        title: `${codeTab} code snippet: ${primaryDataset?.name || "Chart Studio"}`,
        summary: `Chart Studio ${codeTab} code for ${selectedChart?.label || chartType}.`,
        datasetId: primaryDatasetId,
        versionId: primaryVersionId,
        projectId,
        businessQuestion,
        analysisType: `${language}_code_snippet`,
        evidence: {
          chartType,
          columnsUsed: Object.values(roles).filter((value): value is string => typeof value === "string" && Boolean(value)),
          metrics: {
            sourcePage: "chart_studio",
            language: codeTab,
            generatedCode: codeForTab(generatedCode, codeTab),
            userEditedCode: editableCode,
            datasetName: primaryDataset?.name || "",
            roleAssignments: roles,
            linkedProjectId: projectId,
            createdAt: new Date().toISOString(),
            createdBy: "local_user",
          },
        },
      });
      setSavedCharts((current) => [insight, ...current.filter((item) => item.insightId !== insight.insightId)]);
      setStatus(`${codeTab} code snippet saved.`);
    } catch (err) {
      setError(err instanceof Error ? err.message : "ATLAS could not save this code snippet.");
    }
  }

  async function handleExportCodeResult() {
    if (!currentCodeResult) {
      setError("Run code before exporting execution results.");
      return;
    }
    setError("");
    try {
      const resultType = codeTab === "SQL" ? "sql_result" : codeTab === "SAS-compatible" ? "sas_compatible_result" : codeTab === "R" ? "r_result" : "python_result";
      const exported = await exportAnalyticsResultExcel({
        resultType,
        exportTitle: `Chart Studio ${codeTab} Result`,
        datasetName: primaryDataset?.name || "selected_dataset",
        versionId: primaryVersionId,
        businessQuestion,
        resultPayload: currentCodeResult as Record<string, unknown>,
        metadata: { chartType, roles, sourcePage: "chart_studio" },
        createdAt: new Date().toISOString(),
      });
      downloadBlob(exported.blob, exported.filename);
      setStatus(`${codeTab} execution result exported to Excel.`);
    } catch (err) {
      setError(err instanceof Error ? err.message : "ATLAS could not export this execution result.");
    }
  }

  return (
    <div className="atlas-page-shell atlas-theme-chart">
      <section className="atlas-studio-hero">
        <div className="atlas-studio-hero__band">
        <div className="flex flex-col gap-4 2xl:flex-row 2xl:items-center 2xl:justify-between">
          <div>
            <BrandLogo size="md" variant="dark" showSubtitle className="mb-3" />
            <div className="flex items-center gap-2">
              <BarChart3 size={22} className="text-cyan-200" />
              <h1 className="text-2xl font-semibold text-white">ATLAS Chart Studio</h1>
            </div>
            <p className="mt-2 max-w-4xl text-sm leading-6 text-cyan-50/90">
              SAS ODS Graphics Designer-inspired workspace for building governed analytical charts from Dataset Library assets.
            </p>
          </div>
          <div className="grid gap-2 md:grid-cols-4 2xl:min-w-[720px]">
            <HeaderMetric label="Dataset selected" value={primaryDataset?.name || "Select dataset"} />
            <HeaderMetric label="Version selected" value={primaryVersionId || "No version"} />
            <HeaderMetric label="Preview rows" value={String(preview.rows.length)} />
            <HeaderMetric label="Save status" value={status || "Ready"} />
          </div>
        </div>
        </div>
        <div className="atlas-studio-hero__nav">
          <div className="rounded-lg border border-cyan-200 bg-white px-3 py-2 text-xs leading-5 text-cyan-950">
          Chart Studio v1 uses Dataset Library preview/sample rows. Full dataset and warehouse-scale charting will be added later.
          </div>
          <Link to={`/notebook-studio?datasetId=${primaryDatasetId}&versionId=${primaryVersionId}`} className="atlas-studio-chip">
            Send Chart Evidence to Notebook Studio
          </Link>
        </div>
        {status && <div className="mt-4 rounded-lg border border-emerald-200 bg-emerald-50 px-3 py-2 text-sm text-emerald-900">{status}</div>}
        {error && <div className="mt-4 rounded-lg border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-900">{error}</div>}
      </section>

      <section className="grid gap-4 2xl:grid-cols-[340px_minmax(0,1fr)_320px]">
        <aside className="space-y-4">
          <DesignerPanel title="Dataset" icon={<Database size={17} />}>
            <Field label="Dataset Type">
              <select className="atlas-input" value={datasetTypeFilter} onChange={(event) => setDatasetTypeFilter(event.target.value as "all" | "scored_outputs")}>
                <option value="all">All Dataset Library assets</option>
                <option value="scored_outputs">Scored Outputs</option>
              </select>
            </Field>
            <Field label="Primary dataset">
              <select className="atlas-input" value={primaryDatasetId} onChange={(event) => { setPrimaryDatasetId(event.target.value); setPrimaryVersionId(""); }}>
                {displayedDatasets.map((dataset) => <option key={dataset.datasetId} value={dataset.datasetId}>{dataset.name}{isScoredDataset(dataset) ? " - Scored Output" : ""}</option>)}
              </select>
            </Field>
            {selectedDatasetIsScored ? (
              <div className="mb-3 rounded-lg border border-emerald-200 bg-emerald-50 px-3 py-2 text-xs leading-5 text-emerald-900">
                Scored output detected. ATLAS recommends lift/decile, residual diagnostics, score distributions, calibration, and stability charts.
                <Link to={`/model-diagnostics?datasetId=${primaryDatasetId}&versionId=${primaryVersionId}`} className="mt-2 block font-semibold underline">
                  Open in Model Diagnostics
                </Link>
                <Link to="/model-document-studio" className="mt-2 block font-semibold underline">
                  Add Chart to Model Documentation
                </Link>
              </div>
            ) : (
              <div className="mb-3 rounded-lg border border-blue-200 bg-blue-50 px-3 py-2 text-xs leading-5 text-blue-900">
                Scored outputs appear here when a scoring workflow registers actual scored rows to the Dataset Library.
              </div>
            )}
            <Field label="Dataset version">
              <select className="atlas-input" value={primaryVersionId} onChange={(event) => setPrimaryVersionId(event.target.value)}>
                {(primaryDataset?.versions ?? []).map((version) => (
                  <option key={version.versionId} value={version.versionId}>{version.versionId}</option>
                ))}
              </select>
            </Field>
            <div className="grid grid-cols-2 gap-2">
              <Stat label="Preview Rows" value={String(preview.rows.length)} />
              <Stat label="Columns" value={String(preview.columns.length)} />
            </div>
          </DesignerPanel>

          <DesignerPanel title="Data Roles" icon={<GitBranch size={17} />}>
            <RoleEditor chartType={chartType} columns={primaryColumns} numericColumns={numericColumns} categoricalColumns={categoricalColumns} roles={roles} setRoles={setRoles} binning={binning} />
          </DesignerPanel>

          <DesignerPanel title="Chart Properties" icon={<FileSpreadsheet size={17} />}>
            <AggregationSelect value={String(roles.aggregation || "sum")} onChange={(value) => setRoles((current) => ({ ...current, aggregation: value }))} />
            <NumberInput label="Top-N" value={Number(roles.topN || 10)} onChange={(value) => setRoles((current) => ({ ...current, topN: value }))} />
            <NumberInput label="Bins" value={Number(roles.bins || 10)} onChange={(value) => setRoles((current) => ({ ...current, bins: value }))} />
            <div className="mt-3 rounded-xl border border-blue-100 bg-blue-50 p-3">
              <div className="mb-2 text-[11px] font-semibold uppercase tracking-wide text-blue-700">Binning</div>
              <label className="mb-2 flex items-center gap-2 text-sm font-semibold text-slate-700">
                <input type="checkbox" checked={binning.enabled} onChange={(event) => setBinning((current) => ({ ...current, enabled: event.target.checked }))} />
                Enable numeric binning for category roles
              </label>
              <NumberInput label="Number of bins" value={binning.bins} onChange={(value) => setBinning((current) => ({ ...current, bins: Math.max(2, value) }))} />
              <Field label="Bin method">
                <select className="atlas-input" value={binning.method} onChange={(event) => setBinning((current) => ({ ...current, method: event.target.value as BinningMethod }))}>
                  <option value="quantile">Quantile</option>
                  <option value="equal_width">Equal width</option>
                </select>
              </Field>
              <p className="text-xs leading-5 text-blue-900">Recommended for all-numeric datasets. Binned roles create fields such as MedInc_band for grouped charts.</p>
            </div>
            <label className="flex items-center gap-2 rounded-lg border border-slate-200 bg-slate-50 px-3 py-2 text-sm font-semibold text-slate-700">
              <input type="checkbox" checked={showDataTable} onChange={(event) => setShowDataTable(event.target.checked)} />
              Show data table
            </label>
          </DesignerPanel>

          <DesignerPanel title="Filters and Preview Scope" icon={<Database size={17} />}>
            <Field label="Optional secondary dataset">
              <select className="atlas-input" value={secondaryDatasetId} onChange={(event) => setSecondaryDatasetId(event.target.value)}>
                <option value="">None</option>
                {datasets.filter((dataset) => dataset.datasetId !== primaryDatasetId).map((dataset) => <option key={dataset.datasetId} value={dataset.datasetId}>{dataset.name}</option>)}
              </select>
            </Field>
            <Field label="Secondary version">
              <input className="atlas-input" value={secondaryVersionId} onChange={(event) => setSecondaryVersionId(event.target.value)} placeholder="Optional version ID" />
            </Field>
            <Field label="Join key">
              <select className="atlas-input" value={joinKey} onChange={(event) => setJoinKey(event.target.value)}>
                <option value="">No join in v1 preview</option>
                {primaryColumns.map((column) => <option key={column} value={column}>{column}</option>)}
              </select>
            </Field>
          </DesignerPanel>
        </aside>

        <main className="space-y-4">
          <section className="rounded-xl border border-slate-200 bg-white shadow-sm">
            <div className="border-b border-slate-200 px-4 py-3">
              <div className="flex flex-col gap-3 xl:flex-row xl:items-center xl:justify-between">
                <div className="flex items-center gap-2">
                  <BarChart3 size={17} className="text-blue-700" />
                  <h2 className="text-base font-semibold text-slate-950">Graph Gallery</h2>
                </div>
                <div className="flex flex-wrap gap-1">
                  {CHART_FAMILIES.map((family) => (
                    <button
                      key={family.family}
                      type="button"
                      onClick={() => setGalleryTab(family.family)}
                      className={`rounded-full px-3 py-1.5 text-xs font-semibold transition ${galleryTab === family.family ? "bg-slate-950 text-white" : "bg-slate-100 text-slate-600 hover:bg-slate-200"}`}
                    >
                      {family.family}
                    </button>
                  ))}
                </div>
              </div>
            </div>
            <div className="grid gap-3 p-4 md:grid-cols-2 xl:grid-cols-3">
              {activeGallery.charts.map((chart) => {
                const availability = chartAvailability(chart.id, chart.implemented, roles, categoricalColumns, numericColumns, binning);
                return (
                <button
                  key={chart.id}
                  type="button"
                  disabled={!chart.implemented}
                  onClick={() => {
                    setChartType(chart.id);
                    setStatus(`${chart.label} selected.`);
                  }}
                  className={[
                    "group min-h-[190px] rounded-xl border p-3 text-left transition",
                    chartType === chart.id ? "border-blue-500 bg-blue-50 shadow-sm ring-2 ring-blue-100" : "border-slate-200 bg-white hover:border-blue-200 hover:bg-slate-50",
                    !chart.implemented ? "cursor-not-allowed opacity-60" : "",
                  ].join(" ")}
                >
                  <ChartThumbnail type={chart.id} />
                  <div className="mt-3 flex items-start justify-between gap-2">
                    <div>
                      <div className="text-sm font-semibold text-slate-950">{chart.label}</div>
                      <p className="mt-1 text-xs leading-5 text-slate-600">{chart.description}</p>
                    </div>
                    <span className={`shrink-0 rounded-full px-2 py-0.5 text-[10px] font-semibold uppercase ${chart.implemented ? "bg-emerald-100 text-emerald-700" : "bg-slate-100 text-slate-500"}`}>
                      {availability.status}
                    </span>
                  </div>
                  <div className="mt-2 rounded-lg bg-slate-50 px-2 py-1.5 text-[11px] font-semibold text-slate-500">
                    Best for: {chart.bestFor}
                  </div>
                  <div className="mt-2 text-[11px] leading-4 text-slate-500">{availability.reason}</div>
                </button>
              );})}
            </div>
          </section>

          <section className="rounded-xl border border-slate-200 bg-white p-4 shadow-sm">
            <div className="mb-3 flex flex-col gap-3 xl:flex-row xl:items-center xl:justify-between">
              <div>
                <div className="flex items-center gap-2">
                  <Sparkles size={17} className="text-blue-700" />
                  <h2 className="text-base font-semibold text-slate-950">Preview Canvas</h2>
                </div>
                <p className="mt-1 text-sm text-slate-500">{selectedChart?.label || "Chart"} - {primaryDataset?.name || "Dataset"} - {primaryVersionId || "No version selected"}</p>
              </div>
              <div className="flex flex-wrap gap-2">
                <button type="button" onClick={() => setStatus("Preview refreshed.")} className="atlas-secondary-button">Refresh Preview</button>
                <button type="button" onClick={handleExcelExport} className="atlas-secondary-button"><Download size={16} /> Export Chart Data to Excel</button>
                <button type="button" onClick={handleSaveInsight} className="atlas-primary-button"><Save size={16} /> Save Chart as Insight</button>
              </div>
            </div>
            <div className="rounded-2xl border border-slate-200 bg-gradient-to-b from-slate-50 to-white p-4">
              <div className="mb-3 flex items-center justify-between gap-3">
                <div>
                  <h3 className="text-lg font-semibold text-slate-950">{selectedChart?.label || "Chart Preview"}</h3>
                  <p className="text-xs text-slate-500">{primaryDataset?.name || "Dataset"} - Dataset Library preview/sample rows</p>
                </div>
                <span className="rounded-full border border-blue-200 bg-blue-50 px-3 py-1 text-[11px] font-semibold text-blue-700">Preview/sample-row canvas</span>
              </div>
              <ChartPreview chartType={chartType} data={chartData} roles={roles} />
            </div>
            {showDataTable && <ChartDataTable rows={chartData} />}
          </section>

          <section className="rounded-xl border border-slate-200 bg-white shadow-sm">
            <div className="flex flex-col gap-3 border-b border-slate-200 px-4 py-3 xl:flex-row xl:items-center xl:justify-between">
              <div className="flex items-center gap-2">
                <Code2 size={17} className="text-slate-700" />
                <h2 className="text-base font-semibold text-slate-950">Generated Code</h2>
              </div>
              <div className="flex flex-wrap gap-1">
                {(["Python", "SQL", "R", "SAS-compatible"] as const).map((tab) => (
                  <button key={tab} type="button" onClick={() => setCodeTab(tab)} className={`rounded-full px-3 py-1.5 text-xs font-semibold ${codeTab === tab ? "bg-slate-950 text-white" : "bg-slate-100 text-slate-600 hover:bg-slate-200"}`}>
                    {tab}
                  </button>
                ))}
              </div>
            </div>
            <div className="space-y-4 p-4">
              <div className="rounded-xl border border-blue-100 bg-blue-50 px-3 py-2 text-sm text-blue-900">
                Generated code is editable and executable against Dataset Library preview rows. Python runs locally through /api/python/run; SQL runs safely against the preview dataset; R and SAS-compatible use the shared code execution endpoints.
              </div>
              <div className="flex flex-wrap gap-2">
                <button type="button" className="inline-flex items-center gap-2 rounded-lg bg-slate-950 px-3 py-2 text-sm font-semibold text-white disabled:bg-slate-400" disabled={runningCode} onClick={handleRunCode}>
                  <Play size={15} /> {runningCode ? "Running..." : runLabelForTab(codeTab)}
                </button>
                <button type="button" className="atlas-secondary-button" onClick={() => navigator.clipboard?.writeText(editableCode)}><Copy size={15} /> Copy Code</button>
                <button type="button" className="atlas-secondary-button" onClick={() => setUserCode((current) => ({ ...current, [codeTab]: codeForTab(generatedCode, codeTab) }))}><RotateCcw size={15} /> Reset to Generated Code</button>
                <button type="button" className="atlas-secondary-button" onClick={handleSaveCodeSnippet}><Save size={15} /> Save Code Snippet</button>
                <button type="button" className="atlas-secondary-button" disabled={!currentCodeResult} onClick={handleExportCodeResult}><Download size={15} /> Export Result to Excel</button>
              </div>
              <div className="grid gap-4 xl:grid-cols-2">
                <CodeBlock label={`Generated ${codeTab}`} code={codeForTab(generatedCode, codeTab)} />
                <EditableCodeBlock label={`User-edited ${codeTab}`} code={editableCode} onChange={(value) => setUserCode((current) => ({ ...current, [codeTab]: value }))} />
              </div>
              <CodeExecutionResult result={currentCodeResult} />
            </div>
          </section>
        </main>

        <aside className="space-y-4">
          <DesignerPanel title="ATLAS Chart Interpretation" icon={<Sparkles size={17} />}>
            <Field label="Business question">
              <textarea className="atlas-input min-h-[92px]" value={businessQuestion} onChange={(event) => setBusinessQuestion(event.target.value)} />
            </Field>
            <InterpretationPanel interpretation={interpretation} chartType={chartType} />
          </DesignerPanel>

          <DesignerPanel title="Recommended Next Charts" icon={<BarChart3 size={17} />}>
            <RecommendedCharts chartType={chartType} />
          </DesignerPanel>

          <DesignerPanel title="Saved Charts" icon={<Save size={17} />}>
            <div className="grid gap-2">
              {savedCharts.length ? savedCharts.slice(0, 5).map((insight) => (
                <article key={insight.insightId} className="rounded-lg border border-slate-200 bg-slate-50 p-3">
                  <div className="text-sm font-semibold text-slate-950">{insight.title}</div>
                  <p className="mt-1 line-clamp-2 text-xs leading-5 text-slate-600">{insight.summary}</p>
                  <div className="mt-2 text-[11px] font-semibold uppercase tracking-wide text-slate-500">{insight.evidence?.chartType || insight.analysisType}</div>
                </article>
              )) : (
                <div className="rounded-lg border border-slate-200 bg-slate-50 p-3 text-sm text-slate-500">No saved charts for this dataset yet.</div>
              )}
            </div>
          </DesignerPanel>

          <DesignerPanel title="Export Package" icon={<FileSpreadsheet size={17} />}>
            <button type="button" onClick={handleExcelExport} className="atlas-secondary-button w-full"><Download size={16} /> Export Chart Data to Excel</button>
            <button type="button" onClick={handleSaveInsight} className="atlas-primary-button mt-2 w-full"><Save size={16} /> Save Chart as Insight</button>
          </DesignerPanel>
        </aside>
      </section>
    </div>
  );
}

function Card({ title, icon, children }: { title: string; icon?: React.ReactNode; children: React.ReactNode }) {
  return (
    <section className="rounded-xl border border-slate-200 bg-white p-5 shadow-sm">
      <div className="mb-4 flex items-center gap-2 text-slate-900">
        {icon}
        <h2 className="text-base font-semibold">{title}</h2>
      </div>
      {children}
    </section>
  );
}

function DesignerPanel({ title, icon, children }: { title: string; icon?: React.ReactNode; children: React.ReactNode }) {
  return (
    <section className="rounded-xl border border-slate-200 bg-white shadow-sm">
      <div className="flex items-center gap-2 border-b border-slate-200 px-4 py-3 text-slate-900">
        {icon}
        <h2 className="text-sm font-semibold">{title}</h2>
      </div>
      <div className="p-4">{children}</div>
    </section>
  );
}

function HeaderMetric({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-lg border border-slate-200 bg-slate-50 px-3 py-2">
      <div className="text-[10px] font-semibold uppercase tracking-wide text-slate-500">{label}</div>
      <div className="mt-1 truncate text-sm font-semibold text-slate-950" title={value}>{value}</div>
    </div>
  );
}

function ChartThumbnail({ type }: { type: ChartTypeId }) {
  if (type === "correlation_heatmap" || type === "correlation_matrix" || type === "heatmap") {
    return (
      <svg viewBox="0 0 220 88" className="h-20 w-full rounded-lg bg-slate-50">
        {Array.from({ length: 24 }, (_, index) => {
          const x = 24 + (index % 8) * 20;
          const y = 14 + Math.floor(index / 8) * 20;
          const palette = ["#dbeafe", "#93c5fd", "#2563eb", "#fca5a5", "#fee2e2"];
          return <rect key={index} x={x} y={y} width="16" height="16" rx="3" fill={palette[index % palette.length]} />;
        })}
      </svg>
    );
  }
  if (type === "scatter" || type === "grouped_scatter" || type === "residual_diagnostic" || type === "scatter_matrix" || type === "pair_plot") {
    return (
      <svg viewBox="0 0 220 88" className="h-20 w-full rounded-lg bg-slate-50">
        <line x1="24" y1="70" x2="198" y2="70" className="stroke-slate-300" />
        <line x1="24" y1="14" x2="24" y2="70" className="stroke-slate-300" />
        {[18, 32, 41, 55, 74, 92, 118, 142, 160, 184].map((x, index) => <circle key={x} cx={x + 20} cy={64 - ((index * 13) % 48)} r="4" className="fill-blue-600 opacity-70" />)}
        {type === "residual_diagnostic" && <line x1="24" y1="44" x2="198" y2="44" className="stroke-red-400" strokeDasharray="4 4" />}
      </svg>
    );
  }
  if (type === "line" || type === "step" || type === "grouped_line" || type === "forecast" || type === "survival") {
    return (
      <svg viewBox="0 0 220 88" className="h-20 w-full rounded-lg bg-slate-50">
        <line x1="24" y1="70" x2="198" y2="70" className="stroke-slate-300" />
        <polyline points={type === "step" ? "28,60 60,60 60,44 92,44 92,52 124,52 124,28 164,28 164,36 194,36" : "28,62 58,48 86,54 116,32 150,38 194,20"} fill="none" stroke="#2563eb" strokeWidth="4" strokeLinecap="round" strokeLinejoin="round" />
        {type === "forecast" && <path d="M150 38 C168 30 180 26 196 22" fill="none" stroke="#38bdf8" strokeWidth="4" strokeDasharray="5 5" />}
      </svg>
    );
  }
  if (type === "histogram" || type === "bar" || type === "horizontal_bar" || type === "grouped_bar" || type === "stacked_bar" || type === "pareto" || type === "lift_decile" || type === "means") {
    const bars = [34, 58, 46, 72, 38, 28];
    return (
      <svg viewBox="0 0 220 88" className="h-20 w-full rounded-lg bg-slate-50">
        <line x1="24" y1="72" x2="198" y2="72" className="stroke-slate-300" />
        {bars.map((height, index) => <rect key={index} x={34 + index * 24} y={72 - height} width="15" height={height} rx="4" className="fill-blue-600" />)}
        {type === "pareto" && <polyline points="42,38 66,24 90,18 114,16 138,15 162,14" fill="none" stroke="#0f9f8f" strokeWidth="3" />}
      </svg>
    );
  }
  if (type === "box" || type === "grouped_box") {
    return (
      <svg viewBox="0 0 220 88" className="h-20 w-full rounded-lg bg-slate-50">
        {[34, 88, 142].map((x, index) => (
          <g key={x}>
            <line x1={x} y1="18" x2={x} y2="70" className="stroke-slate-400" />
            <rect x={x - 16} y={28 + index * 4} width="32" height="28" rx="4" className="fill-blue-100 stroke-blue-600" />
            <line x1={x - 16} y1={42 + index * 4} x2={x + 16} y2={42 + index * 4} className="stroke-blue-800" />
          </g>
        ))}
      </svg>
    );
  }
  if (type === "control") {
    return (
      <svg viewBox="0 0 220 88" className="h-20 w-full rounded-lg bg-slate-50">
        <line x1="24" y1="24" x2="198" y2="24" className="stroke-red-300" strokeDasharray="4 4" />
        <line x1="24" y1="44" x2="198" y2="44" className="stroke-emerald-400" strokeDasharray="4 4" />
        <line x1="24" y1="64" x2="198" y2="64" className="stroke-red-300" strokeDasharray="4 4" />
        <polyline points="28,52 54,45 76,56 104,37 132,42 158,28 190,48" fill="none" stroke="#2563eb" strokeWidth="4" strokeLinecap="round" />
      </svg>
    );
  }
  if (type === "waterfall") {
    return (
      <svg viewBox="0 0 220 88" className="h-20 w-full rounded-lg bg-slate-50">
        {[42, 74, 106, 138, 170].map((x, index) => <rect key={x} x={x} y={30 + index * 4} width="18" height={28 - index * 2} rx="3" className={index % 2 ? "fill-red-400" : "fill-emerald-500"} />)}
      </svg>
    );
  }
  if (type === "dual_axis") {
    return (
      <svg viewBox="0 0 220 88" className="h-20 w-full rounded-lg bg-slate-50">
        <polyline points="28,62 58,48 86,54 116,32 150,38 194,20" fill="none" stroke="#2563eb" strokeWidth="4" />
        <polyline points="28,28 58,36 86,30 116,46 150,44 194,58" fill="none" stroke="#0f9f8f" strokeWidth="4" />
      </svg>
    );
  }
  if (type === "sankey" || type === "network") {
    return (
      <svg viewBox="0 0 220 88" className="h-20 w-full rounded-lg bg-slate-50">
        <path d="M34 24 C82 24 112 56 178 56" fill="none" stroke="#93c5fd" strokeWidth="12" strokeLinecap="round" />
        <path d="M34 62 C86 62 116 28 178 28" fill="none" stroke="#2563eb" strokeWidth="8" strokeLinecap="round" opacity=".75" />
        {[34, 178].map((x) => <circle key={x} cx={x} cy={24} r="7" className="fill-slate-700" />)}
        {[34, 178].map((x) => <circle key={`${x}-b`} cx={x} cy={62} r="7" className="fill-slate-700" />)}
      </svg>
    );
  }
  return (
    <svg viewBox="0 0 220 88" className="h-20 w-full rounded-lg bg-slate-50">
      <rect x="34" y="24" width="48" height="40" rx="8" className="fill-blue-100 stroke-blue-500" />
      <rect x="92" y="18" width="48" height="52" rx="8" className="fill-emerald-100 stroke-emerald-500" />
      <rect x="150" y="30" width="38" height="28" rx="8" className="fill-slate-100 stroke-slate-400" />
    </svg>
  );
}

function InterpretationPanel({ interpretation, chartType }: { interpretation: string; chartType: ChartTypeId }) {
  const next = nextChartRecommendations(chartType);
  return (
    <div className="space-y-3">
      <div className="rounded-xl border border-emerald-200 bg-emerald-50 p-4 text-sm leading-6 text-emerald-950">
        <div className="mb-2 text-xs font-semibold uppercase tracking-wide text-emerald-700">What this chart shows</div>
        {interpretation}
      </div>
      <div className="rounded-xl border border-slate-200 bg-slate-50 p-3 text-xs leading-5 text-slate-600">
        <div className="font-semibold text-slate-900">What to inspect</div>
        <ul className="mt-1 list-disc space-y-1 pl-4">
          {next.inspect.map((item) => <li key={item}>{item}</li>)}
        </ul>
      </div>
      <div className="rounded-xl border border-amber-200 bg-amber-50 p-3 text-xs leading-5 text-amber-900">
        <div className="font-semibold">Caution</div>
        Preview/sample-row results should be confirmed with the full governed dataset before production reporting.
      </div>
    </div>
  );
}

function RecommendedCharts({ chartType }: { chartType: ChartTypeId }) {
  const recommendations = nextChartRecommendations(chartType).charts;
  return (
    <div className="grid gap-2">
      {recommendations.map((item) => (
        <div key={item} className="rounded-lg border border-slate-200 bg-slate-50 px-3 py-2 text-sm font-semibold text-slate-700">
          {item}
        </div>
      ))}
    </div>
  );
}

function nextChartRecommendations(chartType: ChartTypeId) {
  if (chartType === "scatter") return { charts: ["Add regression fit", "Review correlation heatmap", "Check residual diagnostics"], inspect: ["Nonlinear shape", "Outliers", "Segmented behavior"] };
  if (chartType === "pareto") return { charts: ["Create grouped bar chart", "Export top-N table", "Review concentration by segment"], inspect: ["Top category share", "Cumulative contribution", "Small categories to group"] };
  if (chartType === "control") return { charts: ["Review points outside limits", "Check time ordering", "Create line chart by segment"], inspect: ["Out-of-control points", "Runs above center", "Data-quality artifacts"] };
  if (chartType === "correlation_heatmap") return { charts: ["Create scatter plot", "Review pair plot", "Check residual diagnostics"], inspect: ["Strong positive relationships", "Strong negative relationships", "Potential multicollinearity"] };
  return { charts: ["Review correlation heatmap", "Create Pareto chart", "Export chart data to Excel"], inspect: ["Ranking", "Concentration", "Outliers and missing categories"] };
}

function codeForTab(code: { python: string; sql: string; r: string; sas: string }, tab: "Python" | "SQL" | "R" | "SAS-compatible") {
  if (tab === "SQL") return code.sql;
  if (tab === "R") return code.r;
  if (tab === "SAS-compatible") return code.sas;
  return code.python;
}

function chartAvailability(chartType: ChartTypeId, implemented: boolean, roles: ChartStudioRoleAssignments, categoricalColumns: string[], numericColumns: string[], binning: BinningConfig) {
  if (!implemented) return { status: "Coming soon", reason: comingSoonReason(chartType) };
  if (!categoricalColumns.length && !numericColumns.length) return { status: "Needs data", reason: "Select a dataset with preview columns before building this chart." };
  if (["scatter", "histogram", "density", "box", "correlation_heatmap", "correlation_matrix", "scatter_matrix", "pair_plot", "control", "dual_axis", "residual_diagnostic", "lift_decile", "forecast", "survival"].includes(chartType) && numericColumns.length === 0) {
    return { status: "Unsupported by current data", reason: "This chart requires numeric fields, but none were detected in the selected dataset." };
  }
  const hasCategoryPath = categoricalColumns.length > 0 || (binning.enabled && numericColumns.length > 0);
  if (["bar", "horizontal_bar", "stacked_bar", "grouped_bar", "grouped_box", "grouped_line", "heatmap", "pareto", "waterfall", "box", "means", "panel_category", "panel_time", "small_multiples", "comparison_panels"].includes(chartType) && !hasCategoryPath) {
    return { status: "Needs category", reason: "No categorical fields detected. Enable numeric binning or select a dataset with category fields." };
  }
  if (["correlation_matrix", "scatter_matrix", "pair_plot"].includes(chartType) && numericColumns.length < 2) {
    return { status: "Unsupported by current data", reason: "This matrix chart requires at least two numeric fields." };
  }
  if (chartType === "heatmap" && (!roles.x || !roles.y || !roles.measure)) {
    return { status: "Needs roles", reason: "Select X category, Y category, and a measure to create the heatmap matrix." };
  }
  if (chartType === "grouped_line" && (!roles.x || !roles.measure || !roles.color)) {
    return { status: "Needs roles", reason: "Select an order field, a measure, and a group field for multiple trend lines." };
  }
  if (["panel_time", "comparison_panels"].includes(chartType) && (!roles.panel || !roles.x || !roles.measure)) {
    return { status: "Needs roles", reason: "Select panel, x/order, and measure roles to build comparison panels." };
  }
  if (chartType === "sankey" && (!roles.source || !roles.target)) {
    return { status: "Needs source and target", reason: "Select source and target fields, or use a dataset with flow-style columns." };
  }
  if (chartType === "residual_diagnostic" && (!roles.actual || !roles.predicted)) {
    return { status: "Needs roles", reason: "Select actual and predicted fields to preview residual diagnostics." };
  }
  if (chartType === "lift_decile" && (!roles.score || !roles.outcome)) {
    return { status: "Needs roles", reason: "Select a score/probability field and binary actual outcome to calculate lift." };
  }
  if (chartType === "forecast" && (!roles.x || !roles.measure)) {
    return { status: "Needs roles", reason: "Select a time/order field and measure to generate the simple forecast preview." };
  }
  if (chartType === "survival" && (!roles.duration || !roles.event)) {
    return { status: "Needs roles", reason: "Select duration and event indicator fields to estimate a v1 survival curve." };
  }
  if (chartType === "control" && (!roles.x || !roles.measure)) {
    return { status: "Needs time/order", reason: "Select a time/order role and measure to enable this chart." };
  }
  if (chartType === "scatter" && (!roles.x || !roles.y)) {
    return { status: "Needs roles", reason: "Select X and Y variables to preview this chart." };
  }
  return { status: "Working", reason: "This chart is implemented. Select or adjust roles to update the preview." };
}

function comingSoonReason(chartType: ChartTypeId) {
  if (chartType === "custom") return "Coming soon: custom renderer infrastructure is not implemented yet.";
  if (chartType === "custom_roles") return "Coming soon: user-defined visual encodings require a custom role-mapping engine.";
  if (chartType === "saved_template") return "Coming soon: governed saved template infrastructure is not implemented yet.";
  if (chartType === "network") return "Coming soon: this requires a network or edge-list renderer rather than a standard preview-row chart.";
  return "Coming soon: this chart renderer is not implemented yet.";
}

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <label className="mb-3 block">
      <span className="mb-1 block text-[11px] font-semibold uppercase tracking-wide text-slate-500">{label}</span>
      {children}
    </label>
  );
}

function Stat({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-lg border border-slate-200 bg-slate-50 p-3">
      <div className="text-[10px] font-semibold uppercase tracking-wide text-slate-500">{label}</div>
      <div className="mt-1 text-lg font-semibold text-slate-950">{value}</div>
    </div>
  );
}

function RoleEditor({ chartType, columns, numericColumns, categoricalColumns, roles, setRoles, binning }: {
  chartType: ChartTypeId;
  columns: string[];
  numericColumns: string[];
  categoricalColumns: string[];
  roles: ChartStudioRoleAssignments;
  binning: BinningConfig;
  setRoles: (roles: ChartStudioRoleAssignments | ((current: ChartStudioRoleAssignments) => ChartStudioRoleAssignments)) => void;
}) {
  const update = (key: string, value: string | number | string[]) => setRoles((current) => ({ ...current, [key]: value }));
  const select = (key: string, label: string, options = columns) => (
    <Field label={label}>
      <select className="atlas-input" value={String(roles[key] || "")} onChange={(event) => update(key, event.target.value)}>
        <option value="">Select...</option>
        {options.map((column) => <option key={column} value={column}>{column}</option>)}
      </select>
    </Field>
  );
  const roleSelect = (key: string, label: string, mode: "category" | "color" | "any" = "any") => (
    <Field label={label}>
      <select className="atlas-input" value={String(roles[key] || "")} onChange={(event) => update(key, event.target.value)}>
        {mode === "color" && <option value="">None</option>}
        {mode !== "color" && <option value="">Select...</option>}
        {(mode === "category" || mode === "color") && categoricalColumns.length > 0 && (
          <optgroup label="Categorical fields">
            {categoricalColumns.map((column) => <option key={column} value={column}>{column}</option>)}
          </optgroup>
        )}
        {(mode === "category" || mode === "color") && binning.enabled && numericColumns.length > 0 && (
          <optgroup label="Binned numeric fields">
            {numericColumns.map((column) => <option key={binnedRoleValue(column)} value={binnedRoleValue(column)}>{column}, binned into {binning.method === "quantile" ? "quantiles" : "equal-width bands"}</option>)}
          </optgroup>
        )}
        {mode === "category" && numericColumns.length > 0 && (
          <optgroup label="Numeric fields as discrete categories">
            {numericColumns.map((column) => <option key={`${column}-discrete`} value={column}>{column} as discrete category</option>)}
          </optgroup>
        )}
        {mode === "any" && (
          <>
            {columns.length > 0 && <optgroup label="Generated fields">{columns.map((column) => <option key={column} value={column}>{column}</option>)}</optgroup>}
          </>
        )}
      </select>
    </Field>
  );
  if (chartType === "scatter") return <>{select("x", "X numeric", numericColumns)}{select("y", "Y numeric", numericColumns)}{roleSelect("color", "Color group optional", "color")}{select("label", "Label optional", columns)}</>;
  if (chartType === "histogram" || chartType === "density") return <>{select("numeric", "Numeric variable", numericColumns)}{roleSelect("color", "Group optional", "color")}<NumberInput label="Bins" value={Number(roles.bins || 10)} onChange={(value) => update("bins", value)} /></>;
  if (chartType === "box") return <>{select("measure", "Numeric measure", numericColumns)}{roleSelect("group", "Group variable", "category")}</>;
  if (chartType === "correlation_heatmap" || chartType === "correlation_matrix" || chartType === "scatter_matrix" || chartType === "pair_plot") return <>{<MultiSelect label="Numeric variables" values={(roles.numericVariables as string[]) || numericColumns.slice(0, 6)} options={numericColumns} onChange={(value) => update("numericVariables", value)} />}{roleSelect("color", "Color group optional", "color")}</>;
  if (chartType === "residual_diagnostic") return <>{select("actual", "Actual value", numericColumns)}{select("predicted", "Predicted value", numericColumns)}{select("x", "Observation / order optional", columns)}{roleSelect("color", "Segment optional", "color")}</>;
  if (chartType === "lift_decile") return <>{select("score", "Score / probability", numericColumns)}{select("outcome", "Actual outcome", columns)}<Field label="Positive class value"><input className="atlas-input" value={String(roles.positiveClass ?? "1")} onChange={(event) => update("positiveClass", event.target.value)} /></Field>{select("weight", "Weight optional", numericColumns)}<NumberInput label="Number of deciles" value={Number(roles.deciles || roles.bins || 10)} onChange={(value) => update("deciles", value)} /></>;
  if (chartType === "forecast") return <>{select("x", "Time / order variable", columns)}{select("measure", "Measure", numericColumns)}{roleSelect("group", "Group optional", "color")}<NumberInput label="Forecast horizon" value={Number(roles.horizon || 6)} onChange={(value) => update("horizon", value)} /><AggregationSelect value={String(roles.aggregation || "mean")} onChange={(value) => update("aggregation", value)} /></>;
  if (chartType === "survival") return <>{select("duration", "Duration / time-to-event", numericColumns)}{select("event", "Event indicator", columns)}{roleSelect("group", "Group optional", "color")}</>;
  if (chartType === "data_profile" || chartType === "data_profile_matrix") return <>{<MultiSelect label="Numeric variables" values={(roles.numericVariables as string[]) || numericColumns.slice(0, 8)} options={numericColumns} onChange={(value) => update("numericVariables", value)} />}{select("target", "Target optional", columns)}{roleSelect("group", "Group optional", "color")}</>;
  if (chartType === "grouped_bar" || chartType === "stacked_bar") return <>{roleSelect("category", "Category", "category")}{select("measure", "Measure", numericColumns)}{roleSelect("color", "Stack / group", "color")}<AggregationSelect value={String(roles.aggregation || "mean")} onChange={(value) => update("aggregation", value)} /></>;
  if (chartType === "grouped_box") return <>{select("measure", "Numeric measure", numericColumns)}{roleSelect("group", "Group variable", "category")}{roleSelect("color", "Segment optional", "color")}</>;
  if (chartType === "grouped_scatter") return <>{select("x", "X numeric", numericColumns)}{select("y", "Y numeric", numericColumns)}{roleSelect("color", "Group / color", "color")}</>;
  if (chartType === "grouped_line") return <>{select("x", "X / order variable", columns)}{select("measure", "Y measure", numericColumns)}{roleSelect("color", "Group / line", "color")}<AggregationSelect value={String(roles.aggregation || "mean")} onChange={(value) => update("aggregation", value)} /></>;
  if (chartType === "panel_category" || chartType === "small_multiples" || chartType === "panel_time" || chartType === "comparison_panels") return <>{roleSelect("panel", "Panel variable", "category")}{select("x", chartType === "panel_time" ? "Time / order variable" : "X / category", columns)}{select("measure", "Y / measure", numericColumns)}<AggregationSelect value={String(roles.aggregation || "mean")} onChange={(value) => update("aggregation", value)} /></>;
  if (chartType === "heatmap") return <>{roleSelect("x", "X category or binned numeric", "category")}{roleSelect("y", "Y category or binned numeric", "category")}{select("measure", "Measure", numericColumns)}<AggregationSelect value={String(roles.aggregation || "mean")} onChange={(value) => update("aggregation", value)} /></>;
  if (chartType === "pareto") return <>{roleSelect("category", "Category", "category")}{select("measure", "Measure", numericColumns)}<AggregationSelect value={String(roles.aggregation || "sum")} onChange={(value) => update("aggregation", value)} /><NumberInput label="Top-N" value={Number(roles.topN || 10)} onChange={(value) => update("topN", value)} /></>;
  if (chartType === "waterfall") return <>{roleSelect("category", "Step / category", "category")}{select("measure", "Value / change amount", numericColumns)}</>;
  if (chartType === "control") return <>{select("x", "Time / order variable", columns)}{select("measure", "Measure", numericColumns)}</>;
  if (chartType === "dual_axis") return <>{select("x", "X axis", columns)}{select("leftY", "Left Y measure", numericColumns)}{select("rightY", "Right Y measure", numericColumns)}<AggregationSelect value={String(roles.aggregation || "mean")} onChange={(value) => update("aggregation", value)} /></>;
  if (chartType === "sankey") return <>{roleSelect("source", "Source", "category")}{roleSelect("target", "Target", "category")}{select("weight", "Weight", numericColumns)}</>;
  return <>{roleSelect("category", chartType === "horizontal_bar" ? "Ranked category" : "Category", "category")}{select("measure", "Measure", numericColumns)}<AggregationSelect value={String(roles.aggregation || (chartType === "means" ? "mean" : "sum"))} onChange={(value) => update("aggregation", value)} />{roleSelect("color", "Color group optional", "color")}<NumberInput label="Top-N" value={Number(roles.topN || 10)} onChange={(value) => update("topN", value)} /></>;
}

function AggregationSelect({ value, onChange }: { value: string; onChange: (value: string) => void }) {
  return (
    <Field label="Aggregation">
      <select className="atlas-input" value={value} onChange={(event) => onChange(event.target.value)}>
        <option value="sum">Sum</option>
        <option value="mean">Mean</option>
        <option value="median">Median</option>
        <option value="count">Count</option>
      </select>
    </Field>
  );
}

function NumberInput({ label, value, onChange }: { label: string; value: number; onChange: (value: number) => void }) {
  return (
    <Field label={label}>
      <input className="atlas-input" type="number" value={value} min={1} onChange={(event) => onChange(Number(event.target.value || 1))} />
    </Field>
  );
}

function MultiSelect({ label, values, options, onChange }: { label: string; values: string[]; options: string[]; onChange: (value: string[]) => void }) {
  return (
    <Field label={label}>
      <select className="atlas-input min-h-[120px]" multiple value={values} onChange={(event) => onChange(Array.from(event.target.selectedOptions).map((option) => option.value))}>
        {options.map((option) => <option key={option} value={option}>{option}</option>)}
      </select>
    </Field>
  );
}

function ChartPreview({ chartType, data, roles }: { chartType: ChartTypeId; data: ChartRow[]; roles: ChartStudioRoleAssignments }) {
  if (!data.length) return <EmptyChart message="Select roles to preview this chart." />;
  if (chartType === "residual_diagnostic") return <ResidualDiagnosticsPreview data={data} />;
  if (chartType === "lift_decile") return <LiftDecilePreview data={data} />;
  if (chartType === "forecast") return <ForecastPreview data={data} />;
  if (chartType === "survival") return <SurvivalPreview data={data} />;
  if (chartType === "data_profile" || chartType === "data_profile_matrix") return <DataProfilePreview data={data} />;
  if (chartType === "grouped_bar" || chartType === "stacked_bar") return <GroupedBarPreview data={data} />;
  if (chartType === "grouped_scatter") return <ScatterSvg data={data} />;
  if (chartType === "grouped_box") return <BoxSvg data={data} />;
  if (chartType === "panel_category" || chartType === "small_multiples" || chartType === "panel_time" || chartType === "comparison_panels") return <PanelPreview data={data} />;
  if (chartType === "scatter_matrix" || chartType === "pair_plot") return <PairMatrixPreview data={data} />;
  if (chartType === "scatter") return <ScatterSvg data={data} />;
  if (chartType === "line" || chartType === "step" || chartType === "grouped_line" || chartType === "dual_axis" || chartType === "control") return <LineSvg data={data} chartType={chartType} />;
  if (chartType === "histogram" || chartType === "density") return <BarSvg data={data} labelKey="bin" valueKey="count" />;
  if (chartType === "correlation_heatmap" || chartType === "correlation_matrix" || chartType === "heatmap") return <HeatmapSvg data={data} />;
  if (chartType === "box") return <BoxSvg data={data} />;
  if (chartType === "sankey") return <SankeyPreview data={data} />;
  if (chartType === "waterfall") return <WaterfallSvg data={data} />;
  return <BarSvg data={data} labelKey={chartType === "pareto" ? "category" : "category"} valueKey="value" secondaryKey={chartType === "pareto" ? "cumulativePct" : undefined} topN={Number(roles.topN || 10)} />;
}

function EmptyChart({ message }: { message: string }) {
  return <div className="grid min-h-[340px] place-items-center rounded-xl border border-dashed border-slate-300 bg-slate-50 text-sm text-slate-500">{message}</div>;
}

function ResidualDiagnosticsPreview({ data }: { data: ChartRow[] }) {
  const rows = data.filter((row) => row.kind === "residual_row");
  const summary = data.find((row) => row.kind === "fit_summary") || {};
  return (
    <div className="grid min-h-[360px] gap-3 bg-slate-50 p-3 lg:grid-cols-2">
      <ScatterSvg data={rows.map((row) => ({ x: row.predicted, y: row.residual }))} />
      <ScatterSvg data={rows.map((row) => ({ x: row.predicted, y: row.actual }))} />
      <BarSvg data={histogram(rows.map((row) => toNumber(row.residual)), 10)} labelKey="bin" valueKey="count" />
      <div className="rounded-xl border border-slate-200 bg-white p-4">
        <h3 className="text-sm font-semibold text-slate-950">Fit Summary</h3>
        <div className="mt-3 grid grid-cols-2 gap-2">
          {["n", "mae", "rmse", "mse", "rSquared", "meanResidual", "medianResidual", "residualStd"].map((key) => <Stat key={key} label={key} value={formatNumber(toNumber(summary[key]))} />)}
        </div>
      </div>
    </div>
  );
}

function LiftDecilePreview({ data }: { data: ChartRow[] }) {
  return (
    <div className="grid min-h-[360px] gap-3 bg-slate-50 p-3 lg:grid-cols-[1fr_1.2fr]">
      <BarSvg data={data} labelKey="decile" valueKey="lift" secondaryKey="captureRate" topN={12} />
      <div className="overflow-auto rounded-xl border border-slate-200 bg-white">
        <table className="min-w-full text-xs">
          <thead className="bg-slate-100 text-slate-500"><tr>{["Decile", "Count", "Positives", "Response", "Capture", "Lift"].map((h) => <th key={h} className="px-3 py-2 text-left">{h}</th>)}</tr></thead>
          <tbody>{data.map((row) => <tr key={String(row.decile)} className="border-t"><td className="px-3 py-2">{String(row.decile)}</td><td className="px-3 py-2">{String(row.count)}</td><td className="px-3 py-2">{String(row.positives)}</td><td className="px-3 py-2">{formatNumber(toNumber(row.responseRate))}%</td><td className="px-3 py-2">{formatNumber(toNumber(row.captureRate))}%</td><td className="px-3 py-2">{formatNumber(toNumber(row.lift))}</td></tr>)}</tbody>
        </table>
      </div>
    </div>
  );
}

function ForecastPreview({ data }: { data: ChartRow[] }) {
  return (
    <div className="grid min-h-[360px] gap-3 bg-slate-50 p-3">
      <LineSvg data={data.map((row) => ({ x: row.x, value: row.value ?? row.forecast }))} chartType="forecast" />
      <div className="grid gap-2 md:grid-cols-3">
        {data.slice(-6).map((row, index) => <div key={index} className="rounded-xl border border-slate-200 bg-white p-3 text-sm"><div className="font-semibold text-slate-900">{String(row.x)}</div><div className="text-slate-500">{String(row.type)}: {formatNumber(toNumber(row.value ?? row.forecast))}</div></div>)}
      </div>
    </div>
  );
}

function SurvivalPreview({ data }: { data: ChartRow[] }) {
  return (
    <div className="grid min-h-[360px] gap-3 bg-slate-50 p-3 lg:grid-cols-[1.2fr_1fr]">
      <LineSvg data={data.map((row) => ({ x: row.time, value: row.survival }))} chartType="survival" />
      <ChartDataTable rows={data.slice(0, 20)} />
    </div>
  );
}

function DataProfilePreview({ data }: { data: ChartRow[] }) {
  return (
    <div className="min-h-[360px] overflow-auto rounded-xl border border-slate-200 bg-white">
      <table className="min-w-full text-xs">
        <thead className="sticky top-0 bg-slate-100 text-slate-500"><tr>{["Variable", "Missing %", "Distinct", "Mean", "Median", "Std", "Min", "Max", "Target Corr"].map((h) => <th key={h} className="px-3 py-2 text-left">{h}</th>)}</tr></thead>
        <tbody>{data.map((row) => <tr key={String(row.variable)} className="border-t"><td className="px-3 py-2 font-semibold">{String(row.variable)}</td><td className="px-3 py-2">{formatNumber(toNumber(row.missingPct))}%</td><td className="px-3 py-2">{String(row.distinct)}</td><td className="px-3 py-2">{formatNumber(toNumber(row.mean))}</td><td className="px-3 py-2">{formatNumber(toNumber(row.median))}</td><td className="px-3 py-2">{formatNumber(toNumber(row.std))}</td><td className="px-3 py-2">{formatNumber(toNumber(row.min))}</td><td className="px-3 py-2">{formatNumber(toNumber(row.max))}</td><td className="px-3 py-2">{formatNumber(toNumber(row.targetCorrelation))}</td></tr>)}</tbody>
      </table>
    </div>
  );
}

function GroupedBarPreview({ data }: { data: ChartRow[] }) {
  return <BarSvg data={data.map((row) => ({ ...row, category: `${row.category} | ${row.group}` }))} labelKey="category" valueKey="value" topN={20} />;
}

function PanelPreview({ data }: { data: ChartRow[] }) {
  const panels = Array.from(new Set(data.map((row) => String(row.panel)))).slice(0, 6);
  return (
    <div className="grid min-h-[360px] gap-3 bg-slate-50 p-3 md:grid-cols-2 xl:grid-cols-3">
      {panels.map((panel) => <div key={panel} className="rounded-xl border border-slate-200 bg-white p-3"><div className="mb-2 text-sm font-semibold text-slate-900">{panel}</div><BarSvg data={data.filter((row) => String(row.panel) === panel).slice(0, 8)} labelKey="category" valueKey="value" topN={8} /></div>)}
    </div>
  );
}

function PairMatrixPreview({ data }: { data: ChartRow[] }) {
  const labels = Array.from(new Set(data.flatMap((row) => [String(row.x), String(row.y)]))).slice(0, 6);
  return (
    <div className="min-h-[360px] rounded-xl bg-slate-50 p-4">
      <div className="mb-3 text-sm font-semibold text-slate-900">Pairwise relationship matrix</div>
      <div className="grid gap-2" style={{ gridTemplateColumns: `repeat(${Math.max(1, labels.length)}, minmax(72px, 1fr))` }}>
        {labels.flatMap((y) => labels.map((x) => {
          const row = data.find((item) => String(item.x) === x && String(item.y) === y);
          const value = toNumber(row?.value);
          const intensity = Math.min(1, Math.abs(value));
          return (
            <div key={`${x}-${y}`} className="rounded-lg border border-slate-200 bg-white p-2">
              <div className="truncate text-[10px] font-semibold text-slate-500">{x === y ? x : `${x} / ${y}`}</div>
              <div className="mt-2 h-12 rounded" style={{ background: x === y ? "#e2e8f0" : value >= 0 ? `rgba(37,99,235,${0.15 + intensity * 0.75})` : `rgba(225,29,72,${0.15 + intensity * 0.75})` }} />
              <div className="mt-1 text-xs font-semibold text-slate-700">{x === y ? "distribution" : formatNumber(value)}</div>
            </div>
          );
        }))}
      </div>
    </div>
  );
}

function BarSvg({ data, labelKey, valueKey, secondaryKey, topN = 20 }: { data: ChartRow[]; labelKey: string; valueKey: string; secondaryKey?: string; topN?: number }) {
  const rows = data.slice(0, topN);
  const values = rows.map((row) => toNumber(row[valueKey]));
  const maxValue = Math.max(...values.map((value) => Math.abs(value)), 1);
  return (
    <svg viewBox="0 0 760 360" className="h-[360px] w-full rounded-xl bg-slate-50">
      {rows.map((row, index) => {
        const value = toNumber(row[valueKey]);
        const width = Math.max(2, (Math.abs(value) / maxValue) * 560);
        const y = 32 + index * Math.max(16, 280 / Math.max(1, rows.length));
        return (
          <g key={`${String(row[labelKey])}-${index}`}>
            <text x="20" y={y + 12} className="fill-slate-600 text-[11px]">{truncate(String(row[labelKey] ?? ""), 16)}</text>
            <rect x="170" y={y} width={width} height="14" rx="5" className={value >= 0 ? "fill-blue-600" : "fill-red-500"} />
            <text x={180 + width} y={y + 12} className="fill-slate-600 text-[11px]">{formatNumber(value)}</text>
            {secondaryKey && <text x="680" y={y + 12} className="fill-emerald-700 text-[11px]">{formatNumber(toNumber(row[secondaryKey]))}%</text>}
          </g>
        );
      })}
    </svg>
  );
}

function ScatterSvg({ data }: { data: ChartRow[] }) {
  const rows = data.slice(0, 350);
  const xs = rows.map((row) => toNumber(row.x));
  const ys = rows.map((row) => toNumber(row.y));
  const [minX, maxX] = extent(xs);
  const [minY, maxY] = extent(ys);
  return (
    <svg viewBox="0 0 760 360" className="h-[360px] w-full rounded-xl bg-slate-50">
      <line x1="60" y1="310" x2="720" y2="310" className="stroke-slate-300" />
      <line x1="60" y1="30" x2="60" y2="310" className="stroke-slate-300" />
      {rows.map((row, index) => (
        <circle key={index} cx={scale(toNumber(row.x), minX, maxX, 70, 710)} cy={scale(toNumber(row.y), minY, maxY, 300, 40)} r="3.2" className="fill-blue-600 opacity-70" />
      ))}
    </svg>
  );
}

function LineSvg({ data, chartType }: { data: ChartRow[]; chartType: ChartTypeId }) {
  const rows = data.slice(0, 80);
  const values = rows.map((row) => toNumber(row.value ?? row.leftValue));
  const [minY, maxY] = extent(values);
  const points = rows.map((row, index) => `${scale(index, 0, Math.max(1, rows.length - 1), 60, 720)},${scale(toNumber(row.value ?? row.leftValue), minY, maxY, 300, 40)}`).join(" ");
  const center = chartType === "control" ? toNumber(rows[0]?.center) : null;
  const ucl = chartType === "control" ? toNumber(rows[0]?.ucl) : null;
  const lcl = chartType === "control" ? toNumber(rows[0]?.lcl) : null;
  return (
    <svg viewBox="0 0 760 360" className="h-[360px] w-full rounded-xl bg-slate-50">
      <line x1="60" y1="310" x2="720" y2="310" className="stroke-slate-300" />
      <line x1="60" y1="30" x2="60" y2="310" className="stroke-slate-300" />
      {center != null && <ReferenceLine value={center} minY={minY} maxY={maxY} label="Center" />}
      {ucl != null && <ReferenceLine value={ucl} minY={minY} maxY={maxY} label="UCL" className="stroke-red-400" />}
      {lcl != null && <ReferenceLine value={lcl} minY={minY} maxY={maxY} label="LCL" className="stroke-red-400" />}
      <polyline points={points} fill="none" stroke="#2563eb" strokeWidth="3" strokeLinecap="round" strokeLinejoin="round" />
      {chartType === "dual_axis" && <polyline points={rows.map((row, index) => `${scale(index, 0, Math.max(1, rows.length - 1), 60, 720)},${scale(toNumber(row.rightValue), extent(rows.map((item) => toNumber(item.rightValue)))[0], extent(rows.map((item) => toNumber(item.rightValue)))[1], 300, 40)}`).join(" ")} fill="none" stroke="#0f9f8f" strokeWidth="3" strokeLinecap="round" strokeLinejoin="round" />}
    </svg>
  );
}

function ReferenceLine({ value, minY, maxY, label, className = "stroke-emerald-500" }: { value: number; minY: number; maxY: number; label: string; className?: string }) {
  const y = scale(value, minY, maxY, 300, 40);
  return (
    <g>
      <line x1="60" y1={y} x2="720" y2={y} className={`${className} stroke-dasharray-4`} strokeDasharray="4 4" />
      <text x="625" y={y - 5} className="fill-slate-500 text-[11px]">{label}</text>
    </g>
  );
}

function HeatmapSvg({ data }: { data: ChartRow[] }) {
  const labels = Array.from(new Set(data.flatMap((row) => [String(row.x), String(row.y)]))).slice(0, 12);
  const size = Math.min(32, 300 / Math.max(1, labels.length));
  return (
    <svg viewBox="0 0 760 360" className="h-[360px] w-full rounded-xl bg-slate-50">
      {data.map((row, index) => {
        const x = labels.indexOf(String(row.x));
        const y = labels.indexOf(String(row.y));
        const value = toNumber(row.value);
        const intensity = Math.min(1, Math.abs(value));
        return <rect key={index} x={170 + x * size} y={32 + y * size} width={size - 2} height={size - 2} rx="3" fill={value >= 0 ? `rgba(37,99,235,${0.15 + intensity * 0.75})` : `rgba(225,29,72,${0.15 + intensity * 0.75})`} />;
      })}
      {labels.map((label, index) => <text key={label} x={20} y={50 + index * size} className="fill-slate-500 text-[10px]">{truncate(label, 18)}</text>)}
    </svg>
  );
}

function BoxSvg({ data }: { data: ChartRow[] }) {
  const rows = data.slice(0, 12);
  const [min, max] = extent(rows.flatMap((row) => [toNumber(row.min), toNumber(row.max)]));
  return (
    <svg viewBox="0 0 760 360" className="h-[360px] w-full rounded-xl bg-slate-50">
      {rows.map((row, index) => {
        const y = 40 + index * 24;
        return (
          <g key={index}>
            <text x="20" y={y + 12} className="fill-slate-600 text-[11px]">{truncate(String(row.group), 16)}</text>
            <line x1={scale(toNumber(row.min), min, max, 170, 700)} y1={y + 8} x2={scale(toNumber(row.max), min, max, 170, 700)} y2={y + 8} className="stroke-slate-400" />
            <rect x={scale(toNumber(row.q1), min, max, 170, 700)} y={y} width={Math.max(3, scale(toNumber(row.q3), min, max, 170, 700) - scale(toNumber(row.q1), min, max, 170, 700))} height="16" rx="4" className="fill-blue-200 stroke-blue-500" />
            <line x1={scale(toNumber(row.median), min, max, 170, 700)} y1={y} x2={scale(toNumber(row.median), min, max, 170, 700)} y2={y + 16} className="stroke-blue-800" />
          </g>
        );
      })}
    </svg>
  );
}

function WaterfallSvg({ data }: { data: ChartRow[] }) {
  return <BarSvg data={data.map((row) => ({ ...row, value: row.change }))} labelKey="category" valueKey="value" />;
}

function SankeyPreview({ data }: { data: ChartRow[] }) {
  return (
    <div className="min-h-[340px] rounded-xl bg-slate-50 p-5">
      <div className="grid gap-3">
        {data.slice(0, 12).map((row, index) => (
          <div key={index} className="grid grid-cols-[1fr_auto_1fr] items-center gap-3">
            <div className="rounded-lg border border-slate-200 bg-white px-3 py-2 text-sm font-semibold text-slate-700">{String(row.source)}</div>
            <div className="flex items-center gap-2 text-xs font-semibold text-blue-700">
              <div className="h-2 rounded-full bg-blue-500" style={{ width: `${Math.max(28, toNumber(row.weight) * 4)}px` }} />
              {formatNumber(toNumber(row.weight))}
            </div>
            <div className="rounded-lg border border-slate-200 bg-white px-3 py-2 text-sm font-semibold text-slate-700">{String(row.target)}</div>
          </div>
        ))}
      </div>
    </div>
  );
}

function ChartDataTable({ rows }: { rows: ChartRow[] }) {
  const columns = Array.from(new Set(rows.flatMap((row) => Object.keys(row)))).slice(0, 12);
  return (
    <div className="mt-4 max-h-[260px] overflow-auto rounded-lg border border-slate-200">
      <table className="min-w-full text-xs">
        <thead className="sticky top-0 bg-slate-50 text-slate-500">
          <tr>{columns.map((column) => <th key={column} className="px-3 py-2 text-left">{column}</th>)}</tr>
        </thead>
        <tbody>
          {rows.slice(0, 80).map((row, index) => (
            <tr key={index} className="border-t">
              {columns.map((column) => <td key={column} className="px-3 py-2">{String(row[column] ?? "")}</td>)}
            </tr>
          ))}
        </tbody>
      </table>
      {!rows.length && <div className="p-4 text-sm text-slate-500">No chart data generated yet.</div>}
    </div>
  );
}

function CodeBlock({ label, code }: { label: string; code: string }) {
  return (
    <div>
      <div className="mb-1 text-[11px] font-semibold uppercase tracking-wide text-slate-500">{label}</div>
      <pre className="max-h-[260px] overflow-auto rounded-xl bg-slate-950 p-4 text-xs leading-5 text-slate-100"><code>{code}</code></pre>
    </div>
  );
}

function EditableCodeBlock({ label, code, onChange }: { label: string; code: string; onChange: (value: string) => void }) {
  return (
    <label className="block">
      <span className="mb-1 block text-[11px] font-semibold uppercase tracking-wide text-slate-500">{label}</span>
      <textarea
        className="min-h-[260px] w-full rounded-xl border border-slate-300 bg-white p-4 font-mono text-xs leading-5 text-slate-900 outline-none focus:border-blue-400 focus:ring-2 focus:ring-blue-100"
        value={code}
        onChange={(event) => onChange(event.target.value)}
      />
    </label>
  );
}

function runLabelForTab(tab: CodeTab) {
  if (tab === "SQL") return "Run SQL on Preview";
  if (tab === "R") return "Run R / Validate R Template";
  if (tab === "SAS-compatible") return "Run SAS-Compatible Code";
  return "Run Python";
}

function runnablePython(code: string) {
  return [
    "# ATLAS Chart Studio local-development execution prelude.",
    "try:",
    "    import matplotlib",
    "    matplotlib.use('Agg')",
    "except BaseException:",
    "    pass",
    code,
    "print('ATLAS Chart Studio Python execution completed.')",
  ].join("\n");
}

function isScoredDataset(dataset: Pick<DatasetSummary, "name" | "description" | "sourceType">) {
  return isScoredOutputDataset(dataset as DatasetSummary);
}

function binnedRoleValue(column: string) {
  return `${BINNED_ROLE_PREFIX}${column}`;
}

function isBinnedRole(role: string) {
  return role.startsWith(BINNED_ROLE_PREFIX);
}

function sourceColumnForRole(role: string) {
  return isBinnedRole(role) ? role.slice(BINNED_ROLE_PREFIX.length) : role;
}

function binnedFieldName(role: string) {
  return `${safeName(sourceColumnForRole(role))}_band`;
}

function resolveRoleKey(role: string, roleKeys: Map<string, string>) {
  return roleKeys.get(role) || role;
}

function prepareBinnedRows(rows: ChartRow[], roles: ChartStudioRoleAssignments, binning: BinningConfig) {
  const binnedRoles = Array.from(new Set([
    roles.category,
    roles.group,
    roles.color,
    roles.source,
    roles.target,
  ].map((role) => String(role || "")).filter(isBinnedRole)));
  const roleKeys = new Map<string, string>();
  if (!binning.enabled || !binnedRoles.length) return { rows, roleKeys };

  let prepared = rows.map((row) => ({ ...row }));
  binnedRoles.forEach((role) => {
    const source = sourceColumnForRole(role);
    const field = binnedFieldName(role);
    roleKeys.set(role, field);
    const values = rows.map((row) => toNumber(row[source])).filter(Number.isFinite).sort((a, b) => a - b);
    const binCount = Math.max(2, Math.min(20, Math.floor(binning.bins || 5)));
    const [min, max] = extent(values);
    const breaks = binning.method === "quantile"
      ? Array.from({ length: binCount + 1 }, (_, index) => quantile(values, index / binCount))
      : Array.from({ length: binCount + 1 }, (_, index) => min + ((max - min) * index) / binCount);

    prepared = prepared.map((row) => {
      const value = toNumber(row[source]);
      if (!Number.isFinite(value)) return { ...row, [field]: "Missing" };
      const index = Math.max(0, Math.min(binCount - 1, breaks.findIndex((upper, i) => i > 0 && value <= upper) - 1));
      const lower = breaks[index] ?? min;
      const upper = breaks[index + 1] ?? max;
      const label = `${binning.method === "quantile" ? `Q${index + 1}` : `Band ${index + 1}`}: ${formatNumber(lower)} to ${formatNumber(upper)}`;
      return { ...row, [field]: label };
    });
  });
  return { rows: prepared, roleKeys };
}

function defaultsForChart(chartType: ChartTypeId, current: ChartStudioRoleAssignments, numeric: string[], categorical: string[], columns: string[]) {
  const next = { ...current };
  const firstNum = numeric[0] || columns[0] || "";
  const secondNum = numeric[1] || firstNum;
  const firstCat = categorical[0] || (numeric[0] ? binnedRoleValue(numeric[0]) : columns[0] || "");
  const secondCat = categorical[1] || (numeric[1] ? binnedRoleValue(numeric[1]) : firstCat);
  if (!next.category) next.category = firstCat;
  if (!next.measure) next.measure = firstNum;
  if (!next.x) next.x = chartType === "scatter" ? firstNum : firstCat;
  if (!next.y) next.y = secondNum;
  if (!next.numeric) next.numeric = firstNum;
  if (!next.group) next.group = firstCat;
  if (!next.source) next.source = firstCat;
  if (!next.target) next.target = secondCat;
  if (!next.weight) next.weight = firstNum;
  if (!next.leftY) next.leftY = firstNum;
  if (!next.rightY) next.rightY = secondNum;
  if (!next.actual) next.actual = firstNum;
  if (!next.predicted) next.predicted = secondNum;
  if (!next.score) next.score = firstNum;
  if (!next.outcome) next.outcome = columns[columns.length - 1] || firstCat;
  if (!next.positiveClass) next.positiveClass = "1";
  if (!next.deciles) next.deciles = 10;
  if (!next.horizon) next.horizon = 6;
  if (!next.duration) next.duration = firstNum;
  if (!next.event) next.event = columns[columns.length - 1] || firstCat;
  if (!next.target) next.target = columns[columns.length - 1] || firstNum;
  if (!next.panel) next.panel = firstCat;
  if (!next.numericVariables) next.numericVariables = numeric.slice(0, 6);
  return next;
}

function computeChartData(chartType: ChartTypeId, rows: ChartRow[], roles: ChartStudioRoleAssignments, numericColumns: string[], binning: BinningConfig): ChartRow[] {
  if (!rows.length) return [];
  const prepared = prepareBinnedRows(rows, roles, binning);
  if (chartType === "residual_diagnostic") return residualDiagnosticRows(prepared.rows, String(roles.actual), String(roles.predicted), String(roles.x || ""));
  if (chartType === "lift_decile") return liftDecileRows(prepared.rows, String(roles.score), String(roles.outcome), String(roles.positiveClass ?? "1"), Number(roles.deciles || roles.bins || 10));
  if (chartType === "forecast") return forecastRows(prepared.rows, String(roles.x), String(roles.measure), String(roles.aggregation || "mean"), Number(roles.horizon || 6));
  if (chartType === "survival") return survivalRows(prepared.rows, String(roles.duration), String(roles.event));
  if (chartType === "data_profile" || chartType === "data_profile_matrix") return dataProfileRows(prepared.rows, ((roles.numericVariables as string[]) || numericColumns).slice(0, 12), String(roles.target || ""));
  if (chartType === "correlation_matrix" || chartType === "scatter_matrix" || chartType === "pair_plot") return correlationRows(rows, ((roles.numericVariables as string[]) || numericColumns).slice(0, 6));
  if (chartType === "heatmap") return heatmapRows(prepared.rows, resolveRoleKey(String(roles.x), prepared.roleKeys), resolveRoleKey(String(roles.y), prepared.roleKeys), String(roles.measure), String(roles.aggregation || "mean"));
  if (chartType === "grouped_bar" || chartType === "stacked_bar") return groupedSegmentRows(prepared.rows, resolveRoleKey(String(roles.category), prepared.roleKeys), resolveRoleKey(String(roles.color), prepared.roleKeys), String(roles.measure), String(roles.aggregation || "mean"));
  if (chartType === "grouped_box") return boxPlot(prepared.rows, resolveRoleKey(String(roles.group), prepared.roleKeys), String(roles.measure));
  if (chartType === "grouped_scatter") return prepared.rows.map((row) => ({ x: toNumber(row[String(roles.x)]), y: toNumber(row[String(roles.y)]), color: row[resolveRoleKey(String(roles.color || ""), prepared.roleKeys)] })).filter((row) => Number.isFinite(row.x) && Number.isFinite(row.y));
  if (chartType === "grouped_line") return groupedLineRows(prepared.rows, String(roles.x), String(roles.measure), resolveRoleKey(String(roles.color), prepared.roleKeys), String(roles.aggregation || "mean"));
  if (chartType === "panel_category" || chartType === "small_multiples" || chartType === "panel_time" || chartType === "comparison_panels") return panelRows(prepared.rows, resolveRoleKey(String(roles.panel), prepared.roleKeys), String(roles.x), String(roles.measure), String(roles.aggregation || "mean"));
  if (chartType === "scatter") return prepared.rows.map((row) => ({ x: toNumber(row[String(roles.x)]), y: toNumber(row[String(roles.y)]), color: row[resolveRoleKey(String(roles.color || ""), prepared.roleKeys)], label: row[String(roles.label || "")] })).filter((row) => Number.isFinite(row.x) && Number.isFinite(row.y));
  if (chartType === "histogram" || chartType === "density") return histogram(rows.map((row) => toNumber(row[String(roles.numeric)])).filter(Number.isFinite), Number(roles.bins || 10)).map((row, index, all) => chartType === "density" ? { ...row, count: smoothedCount(all, index) } : row);
  if (chartType === "box") return boxPlot(prepared.rows, resolveRoleKey(String(roles.group), prepared.roleKeys), String(roles.measure));
  if (chartType === "correlation_heatmap") return correlationRows(rows, ((roles.numericVariables as string[]) || numericColumns).slice(0, 10));
  if (chartType === "waterfall") return groupedAggregate(prepared.rows, resolveRoleKey(String(roles.category), prepared.roleKeys), String(roles.measure), "sum", Number(roles.topN || 20)).map((row, index, all) => ({ ...row, change: row.value, cumulative: all.slice(0, index + 1).reduce((sum, item) => sum + toNumber(item.value), 0) }));
  if (chartType === "control") return controlRows(rows, String(roles.x), String(roles.measure));
  if (chartType === "dual_axis") return dualAxisRows(rows, String(roles.x), String(roles.leftY), String(roles.rightY), String(roles.aggregation || "mean"));
  if (chartType === "sankey") return flowRows(prepared.rows, resolveRoleKey(String(roles.source), prepared.roleKeys), resolveRoleKey(String(roles.target), prepared.roleKeys), String(roles.weight));
  const categoryRole = String(roles.category);
  const grouped = groupedAggregate(prepared.rows, resolveRoleKey(categoryRole, prepared.roleKeys), String(roles.measure), String(roles.aggregation || "sum"), Number(roles.topN || 10), isBinnedRole(categoryRole));
  if (chartType === "pareto") {
    const total = grouped.reduce((sum, row) => sum + Math.max(0, toNumber(row.value)), 0) || 1;
    let running = 0;
    return grouped.map((row) => {
      running += Math.max(0, toNumber(row.value));
      return { ...row, cumulativePct: (running / total) * 100 };
    });
  }
  if (chartType === "line") return grouped.map((row) => ({ x: row.category, value: row.value }));
  if (chartType === "step") return grouped.map((row) => ({ x: row.category, value: row.value }));
  if (chartType === "means") return groupedAggregate(prepared.rows, resolveRoleKey(String(roles.category), prepared.roleKeys), String(roles.measure), "mean", Number(roles.topN || 10), isBinnedRole(categoryRole));
  return grouped;
}

function residualDiagnosticRows(rows: ChartRow[], actualKey: string, predictedKey: string, orderKey: string): ChartRow[] {
  const residualRows = rows.map((row, index) => {
    const actual = toNumber(row[actualKey]);
    const predicted = toNumber(row[predictedKey]);
    const residual = actual - predicted;
    return { kind: "residual_row", order: row[orderKey] ?? index + 1, actual, predicted, residual, absResidual: Math.abs(residual), squaredResidual: residual ** 2, percentError: actual ? residual / actual : 0 };
  }).filter((row) => Number.isFinite(row.actual) && Number.isFinite(row.predicted)).slice(0, 600);
  if (!residualRows.length) return [];
  const actuals = residualRows.map((row) => row.actual);
  const residuals = residualRows.map((row) => row.residual);
  const squared = residualRows.map((row) => row.squaredResidual);
  const meanActual = aggregate(actuals, "mean");
  const sst = actuals.reduce((sum, value) => sum + (value - meanActual) ** 2, 0);
  const sse = squared.reduce((sum, value) => sum + value, 0);
  return [{ kind: "fit_summary", n: residualRows.length, mae: aggregate(residualRows.map((row) => row.absResidual), "mean"), mse: aggregate(squared, "mean"), rmse: Math.sqrt(aggregate(squared, "mean")), rSquared: sst ? 1 - sse / sst : 0, meanResidual: aggregate(residuals, "mean"), medianResidual: aggregate(residuals, "median"), residualStd: standardDeviation(residuals) }, ...residualRows];
}

function liftDecileRows(rows: ChartRow[], scoreKey: string, outcomeKey: string, positiveClass: string, deciles: number): ChartRow[] {
  const scored = rows.map((row) => ({ score: toNumber(row[scoreKey]), positive: String(row[outcomeKey]) === positiveClass || toNumber(row[outcomeKey]) === toNumber(positiveClass) ? 1 : 0 })).filter((row) => Number.isFinite(row.score)).sort((a, b) => b.score - a.score);
  if (!scored.length) return [];
  const bins = Math.max(2, Math.min(20, Math.floor(deciles || 10)));
  const totalPositives = scored.reduce((sum, row) => sum + row.positive, 0) || 1;
  const baseline = totalPositives / scored.length || 1;
  let cumulative = 0;
  return Array.from({ length: bins }, (_, index) => {
    const start = Math.floor((index * scored.length) / bins);
    const end = Math.floor(((index + 1) * scored.length) / bins);
    const slice = scored.slice(start, end);
    const positives = slice.reduce((sum, row) => sum + row.positive, 0);
    cumulative += positives;
    const responseRate = slice.length ? positives / slice.length : 0;
    return { decile: index + 1, count: slice.length, positives, responseRate: responseRate * 100, cumulativePositives: cumulative, captureRate: (cumulative / totalPositives) * 100, lift: baseline ? responseRate / baseline : 0 };
  });
}

function forecastRows(rows: ChartRow[], xKey: string, measureKey: string, aggregation: string, horizon: number): ChartRow[] {
  const historical = groupedAggregate(rows, xKey, measureKey, aggregation, 120, true).map((row, index) => ({ type: "Historical", x: row.category, value: row.value, index }));
  if (historical.length < 2) return historical;
  const values = historical.map((row) => toNumber(row.value));
  const slope = (values[values.length - 1] - values[0]) / Math.max(1, values.length - 1);
  const forecast = Array.from({ length: Math.max(1, Math.min(24, horizon)) }, (_, i) => ({ type: "Forecast", x: `F+${i + 1}`, forecast: values[values.length - 1] + slope * (i + 1), index: historical.length + i }));
  return [...historical, ...forecast];
}

function survivalRows(rows: ChartRow[], durationKey: string, eventKey: string): ChartRow[] {
  const ordered = rows.map((row) => ({ duration: toNumber(row[durationKey]), event: toNumber(row[eventKey]) > 0 ? 1 : 0 })).filter((row) => Number.isFinite(row.duration)).sort((a, b) => a.duration - b.duration);
  let atRisk = ordered.length;
  let survival = 1;
  const byTime = new Map<number, { events: number; censored: number }>();
  ordered.forEach((row) => {
    const current = byTime.get(row.duration) || { events: 0, censored: 0 };
    if (row.event) current.events += 1;
    else current.censored += 1;
    byTime.set(row.duration, current);
  });
  return Array.from(byTime.entries()).map(([time, counts]) => {
    if (atRisk > 0) survival *= 1 - counts.events / atRisk;
    const output = { time, atRisk, events: counts.events, censored: counts.censored, survival: survival * 100 };
    atRisk -= counts.events + counts.censored;
    return output;
  }).slice(0, 120);
}

function dataProfileRows(rows: ChartRow[], columns: string[], targetKey: string): ChartRow[] {
  return columns.map((column) => {
    const values = rows.map((row) => toNumber(row[column])).filter(Number.isFinite).sort((a, b) => a - b);
    const missing = rows.length - values.length;
    return { variable: column, missingPct: rows.length ? (missing / rows.length) * 100 : 0, distinct: new Set(rows.map((row) => row[column])).size, mean: aggregate(values, "mean"), median: aggregate(values, "median"), std: standardDeviation(values), min: values[0] ?? 0, max: values[values.length - 1] ?? 0, targetCorrelation: targetKey ? correlation(rows.map((row) => toNumber(row[column])), rows.map((row) => toNumber(row[targetKey]))) : 0 };
  });
}

function groupedSegmentRows(rows: ChartRow[], categoryKey: string, groupKey: string, measureKey: string, aggregation: string): ChartRow[] {
  const groups = new Map<string, number[]>();
  rows.forEach((row) => {
    const category = String(row[categoryKey] ?? "Missing");
    const group = String(row[groupKey] ?? "All");
    const value = aggregation === "count" ? 1 : toNumber(row[measureKey]);
    if (!Number.isFinite(value)) return;
    const key = `${category}|||${group}`;
    groups.set(key, [...(groups.get(key) || []), value]);
  });
  return Array.from(groups.entries()).map(([key, values]) => {
    const [category, group] = key.split("|||");
    return { category, group, value: aggregate(values, aggregation), count: values.length };
  }).sort((a, b) => Math.abs(toNumber(b.value)) - Math.abs(toNumber(a.value))).slice(0, 30);
}

function groupedLineRows(rows: ChartRow[], xKey: string, measureKey: string, groupKey: string, aggregation: string): ChartRow[] {
  const groups = Array.from(new Set(rows.map((row) => String(row[groupKey] ?? "All")))).slice(0, 4);
  return groups.flatMap((group) => groupedAggregate(rows.filter((row) => String(row[groupKey] ?? "All") === group), xKey, measureKey, aggregation, 24, true).map((row) => ({ x: row.category, value: row.value, group })));
}

function heatmapRows(rows: ChartRow[], xKey: string, yKey: string, measureKey: string, aggregation: string): ChartRow[] {
  const groups = new Map<string, number[]>();
  rows.forEach((row) => {
    const x = String(row[xKey] ?? "Missing");
    const y = String(row[yKey] ?? "Missing");
    const value = aggregation === "count" ? 1 : toNumber(row[measureKey]);
    if (!Number.isFinite(value)) return;
    const key = `${x}|||${y}`;
    groups.set(key, [...(groups.get(key) || []), value]);
  });
  return Array.from(groups.entries()).slice(0, 144).map(([key, values]) => {
    const [x, y] = key.split("|||");
    return { x, y, value: aggregate(values, aggregation), count: values.length };
  });
}

function smoothedCount(rows: ChartRow[], index: number): number {
  const values = [index - 1, index, index + 1].filter((i) => i >= 0 && i < rows.length).map((i) => toNumber(rows[i].count));
  return aggregate(values, "mean");
}

function panelRows(rows: ChartRow[], panelKey: string, xKey: string, measureKey: string, aggregation: string): ChartRow[] {
  const panels = Array.from(new Set(rows.map((row) => String(row[panelKey] ?? "Missing")))).slice(0, 6);
  return panels.flatMap((panel) => groupedAggregate(rows.filter((row) => String(row[panelKey] ?? "Missing") === panel), xKey, measureKey, aggregation, 8).map((row) => ({ ...row, panel })));
}

function groupedAggregate(rows: ChartRow[], categoryKey: string, measureKey: string, aggregation: string, topN: number, preserveOrder = false): ChartRow[] {
  const groups = new Map<string, number[]>();
  rows.forEach((row) => {
    const category = String(row[categoryKey] ?? "Missing");
    const value = aggregation === "count" ? 1 : toNumber(row[measureKey]);
    if (!Number.isFinite(value)) return;
    groups.set(category, [...(groups.get(category) || []), value]);
  });
  const output = Array.from(groups.entries())
    .map(([category, values]) => ({ category, value: aggregate(values, aggregation), count: values.length, [categoryKey]: category, [`${aggregation}_${measureKey}`]: aggregate(values, aggregation) }));
  return (preserveOrder ? output : output.sort((a, b) => Math.abs(toNumber(b.value)) - Math.abs(toNumber(a.value)))).slice(0, topN);
}

function histogram(values: number[], bins: number): ChartRow[] {
  if (!values.length) return [];
  const [min, max] = extent(values);
  const width = (max - min || 1) / bins;
  return Array.from({ length: bins }, (_, index) => {
    const start = min + index * width;
    const end = index === bins - 1 ? max : start + width;
    const count = values.filter((value) => value >= start && (index === bins - 1 ? value <= end : value < end)).length;
    return { bin: `${formatNumber(start)} to ${formatNumber(end)}`, count, start, end };
  });
}

function boxPlot(rows: ChartRow[], groupKey: string, measureKey: string): ChartRow[] {
  const groups = new Map<string, number[]>();
  rows.forEach((row) => {
    const value = toNumber(row[measureKey]);
    if (!Number.isFinite(value)) return;
    const group = String(row[groupKey] ?? "All");
    groups.set(group, [...(groups.get(group) || []), value]);
  });
  return Array.from(groups.entries()).slice(0, 14).map(([group, values]) => {
    const sorted = values.slice().sort((a, b) => a - b);
    return { group, min: sorted[0], q1: quantile(sorted, 0.25), median: quantile(sorted, 0.5), q3: quantile(sorted, 0.75), max: sorted[sorted.length - 1], count: sorted.length };
  });
}

function correlationRows(rows: ChartRow[], columns: string[]): ChartRow[] {
  const output: ChartRow[] = [];
  columns.forEach((x) => columns.forEach((y) => output.push({ x, y, value: correlation(rows.map((row) => toNumber(row[x])), rows.map((row) => toNumber(row[y]))) })));
  return output;
}

function controlRows(rows: ChartRow[], xKey: string, measureKey: string): ChartRow[] {
  const values = rows.map((row, index) => ({ x: row[xKey] ?? index + 1, value: toNumber(row[measureKey]) })).filter((row) => Number.isFinite(row.value)).slice(0, 80);
  const mean = aggregate(values.map((row) => row.value), "mean");
  const sd = standardDeviation(values.map((row) => row.value));
  return values.map((row) => ({ ...row, center: mean, ucl: mean + 3 * sd, lcl: mean - 3 * sd, status: row.value > mean + 3 * sd || row.value < mean - 3 * sd ? "out_of_control" : "in_control" }));
}

function dualAxisRows(rows: ChartRow[], xKey: string, leftKey: string, rightKey: string, aggregation: string): ChartRow[] {
  const left = groupedAggregate(rows, xKey, leftKey, aggregation, 80);
  const right = groupedAggregate(rows, xKey, rightKey, aggregation, 80);
  const rightMap = new Map(right.map((row) => [row.category, row.value]));
  return left.map((row) => ({ x: row.category, leftValue: row.value, rightValue: rightMap.get(row.category) ?? 0, value: row.value }));
}

function flowRows(rows: ChartRow[], sourceKey: string, targetKey: string, weightKey: string): ChartRow[] {
  const groups = new Map<string, number>();
  rows.forEach((row) => {
    const source = String(row[sourceKey] ?? "Missing");
    const target = String(row[targetKey] ?? "Missing");
    const weight = weightKey ? toNumber(row[weightKey]) : 1;
    if (!Number.isFinite(weight)) return;
    const key = `${source}|||${target}`;
    groups.set(key, (groups.get(key) || 0) + Math.max(0, weight));
  });
  return Array.from(groups.entries()).map(([key, weight]) => {
    const [source, target] = key.split("|||");
    return { source, target, weight };
  }).sort((a, b) => toNumber(b.weight) - toNumber(a.weight)).slice(0, 20);
}

function interpretChart(chartType: ChartTypeId, data: ChartRow[], roles: ChartStudioRoleAssignments, datasetName: string) {
  const caution = "This interpretation is based on Dataset Library preview/sample rows.";
  if (!data.length) return `Assign valid roles to generate an ATLAS chart interpretation. ${caution}`;
  if (chartType === "correlation_heatmap") {
    const strongest = data.filter((row) => row.x !== row.y).sort((a, b) => Math.abs(toNumber(b.value)) - Math.abs(toNumber(a.value)))[0];
    return `The strongest preview-row relationship is ${strongest?.x} vs ${strongest?.y} with correlation ${formatNumber(toNumber(strongest?.value))}. Review full-dataset results before drawing production conclusions. ${caution}`;
  }
  if (chartType === "pareto") {
    const top = data[0];
    return `The top category, ${top?.category}, contributes ${formatNumber(toNumber(top?.value))} to the selected measure. This suggests a concentrated driver pattern in ${datasetName}. ${caution}`;
  }
  if (chartType === "control") {
    const flags = data.filter((row) => row.status === "out_of_control").length;
    return `${flags} preview point(s) are outside the configured control limits. Review whether these represent process shifts or data-quality artifacts. ${caution}`;
  }
  if (chartType === "sankey") {
    const top = data[0];
    return `The largest flow is from ${top?.source} to ${top?.target}. Review whether small flows should be grouped into Other for readability. ${caution}`;
  }
  if (chartType === "residual_diagnostic") return `Residuals should be centered around zero without obvious pattern. Curvature, funnel shape, or large outliers may indicate model bias, heteroskedasticity, or missing nonlinear effects. ${caution}`;
  if (chartType === "lift_decile") return `A useful scoring model should concentrate positive outcomes in the highest score deciles. Review whether lift declines monotonically across deciles. ${caution}`;
  if (chartType === "forecast") return `The forecast is a simple preview trend, not a production forecasting model. Use it to inspect directionality, seasonality hints, and possible breaks before deeper time-series modeling. ${caution}`;
  if (chartType === "survival") return `The survival curve estimates the share of records not yet experiencing the event over time. Compare curves by group to identify earlier or later event timing. ${caution}`;
  if (chartType === "data_profile" || chartType === "data_profile_matrix") return `Data profile summarizes variable distributions, missingness, and relationships to the selected target. Use it to identify skew, outliers, sparse variables, or possible leakage before modeling. ${caution}`;
  if (chartType === "grouped_bar" || chartType === "grouped_box" || chartType === "grouped_scatter") return `Grouped charts compare patterns across segments. Look for segments with meaningfully different levels, slopes, or distributions. ${caution}`;
  if (chartType === "panel_category" || chartType === "small_multiples") return `Panel charts repeat the same analytical view across segments so pattern differences are easier to compare. ${caution}`;
  if (chartType === "scatter") return `The scatter plot compares ${roles.x} and ${roles.y}. Look for nonlinear shape, outliers, and segmented behavior before using the relationship in a governed decision. ${caution}`;
  return `The chart summarizes ${String(roles.measure || roles.numeric || roles.y || "the selected measure")} by ${String(roles.category || roles.x || roles.group || "the selected role")}. Review ranking, concentration, and outliers before sharing the chart as governed evidence. ${caution}`;
}

function generateChartCode(chartType: ChartTypeId, datasetName: string, versionId: string, roles: ChartStudioRoleAssignments, binning: BinningConfig) {
  const table = safeName(datasetName || "selected_dataset");
  const dataRef = `atlas_dataset.${table}_${safeName(versionId || "current")}`;
  const categoryRole = String(roles.category || roles.x || roles.group || "category");
  const category = isBinnedRole(categoryRole) ? binnedFieldName(categoryRole) : categoryRole;
  const sourceCategory = sourceColumnForRole(categoryRole);
  const measure = String(roles.measure || roles.y || roles.numeric || roles.leftY || "measure");
  const aggregation = String(roles.aggregation || "sum");
  const pandasAgg = aggregation === "count" ? "count" : aggregation;
  const pythonBinning = isBinnedRole(categoryRole)
    ? `df["${category}"] = pd.qcut(df["${sourceCategory}"], q=${binning.bins}, duplicates="drop")\n`
    : "";
  const sqlBinning = isBinnedRole(categoryRole)
    ? `-- ATLAS binned ${sourceCategory} into ${binning.method === "quantile" ? "quantile" : "equal-width"} bands for the preview chart.\n-- Exact ${binning.method === "quantile" ? "quantile" : "equal-width"} syntax depends on the production SQL engine.\n`
    : "";
  const sqlCategoryExpr = isBinnedRole(categoryRole) ? `"${sourceCategory}"` : `"${category}"`;
  const rBinning = isBinnedRole(categoryRole)
    ? `df$${category} <- dplyr::ntile(df$${sourceCategory}, ${binning.bins})\n`
    : "";
  const sasBinning = isBinnedRole(categoryRole)
    ? `proc rank data=work.${table} groups=${binning.bins} out=work.${table}_binned;\n    var ${sourceCategory};\n    ranks ${category};\nrun;\n\n`
    : "";
  const sasTable = isBinnedRole(categoryRole) ? `work.${table}_binned` : `work.${table}`;
  if (chartType === "residual_diagnostic") {
    const actual = String(roles.actual || "actual");
    const predicted = String(roles.predicted || "predicted");
    return {
      python: `# ATLAS Residual Diagnostics\nimport pandas as pd\nimport numpy as np\n\ndf["residual"] = df["${actual}"] - df["${predicted}"]\ndf["abs_residual"] = df["residual"].abs()\ndf["squared_residual"] = df["residual"] ** 2\nfit_summary = {\n    "n": len(df),\n    "mae": df["abs_residual"].mean(),\n    "rmse": np.sqrt(df["squared_residual"].mean()),\n    "mse": df["squared_residual"].mean(),\n    "mean_residual": df["residual"].mean(),\n    "median_residual": df["residual"].median(),\n    "residual_std": df["residual"].std()\n}\nprint(fit_summary)\n`,
      sql: `-- ATLAS Residual Diagnostics\nSELECT *,\n  "${actual}" - "${predicted}" AS residual,\n  ABS("${actual}" - "${predicted}") AS abs_residual,\n  POWER("${actual}" - "${predicted}", 2) AS squared_residual\nFROM ${dataRef};`,
      r: `# ATLAS Residual Diagnostics\ndf$residual <- df$${actual} - df$${predicted}\ndf$abs_residual <- abs(df$residual)\ndf$squared_residual <- df$residual ^ 2\nsummary(df[, c("residual", "abs_residual", "squared_residual")])\n`,
      sas: `/* ATLAS Residual Diagnostics */\ndata work.diagnostics;\n    set work.${table};\n    residual = ${actual} - ${predicted};\n    abs_residual = abs(residual);\n    squared_residual = residual * residual;\nrun;\n\nproc means data=work.diagnostics n mean median std min max;\n    var residual abs_residual squared_residual;\nrun;\n\nproc corr data=work.diagnostics;\n    var ${actual} ${predicted} residual;\nrun;\n`,
    };
  }
  if (chartType === "lift_decile") {
    const score = String(roles.score || "score");
    const outcome = String(roles.outcome || "actual");
    const positive = String(roles.positiveClass ?? "1");
    const deciles = Number(roles.deciles || 10);
    return {
      python: `# ATLAS Lift / Decile\nimport pandas as pd\n\ndf = df.sort_values("${score}", ascending=False).copy()\ndf["score_decile"] = pd.qcut(df["${score}"].rank(method="first", ascending=False), q=${deciles}, labels=False, duplicates="drop") + 1\ndf["positive"] = (df["${outcome}"].astype(str) == "${positive}").astype(int)\nchart_data = df.groupby("score_decile")["positive"].agg(["count", "sum", "mean"]).reset_index()\nchart_data["lift"] = chart_data["mean"] / df["positive"].mean()\nprint(chart_data)\n`,
      sql: `-- ATLAS Lift / Decile\nWITH ranked AS (\n  SELECT *, NTILE(${deciles}) OVER (ORDER BY "${score}" DESC) AS score_decile\n  FROM ${dataRef}\n)\nSELECT score_decile, COUNT(*) AS count,\n  SUM(CASE WHEN CAST("${outcome}" AS VARCHAR) = '${positive}' THEN 1 ELSE 0 END) AS positives\nFROM ranked\nGROUP BY score_decile\nORDER BY score_decile;`,
      r: `# ATLAS Lift / Decile\ndf <- df[order(-df$${score}), ]\ndf$score_decile <- dplyr::ntile(-df$${score}, ${deciles})\ndf$positive <- as.integer(as.character(df$${outcome}) == "${positive}")\naggregate(positive ~ score_decile, data = df, FUN = mean)\n`,
      sas: `/* ATLAS Lift / Decile */\nproc rank data=work.${table} groups=${deciles} out=work.deciles descending;\n    var ${score};\n    ranks score_decile;\nrun;\n\nproc means data=work.deciles n mean sum;\n    class score_decile;\n    var ${outcome};\nrun;\n`,
    };
  }
  if (chartType === "forecast") {
    return {
      python: `# ATLAS Simple Forecast Preview\nchart_data = df.groupby("${String(roles.x || "time")}")["${measure}"].${pandasAgg}().reset_index()\nchart_data["moving_average"] = chart_data["${measure}"].rolling(3, min_periods=1).mean()\n# ATLAS renders a simple linear-trend forecast preview for ${Number(roles.horizon || 6)} periods.\n`,
      sql: `-- ATLAS Simple Forecast data prep\nSELECT "${String(roles.x || "time")}" AS time_order, ${aggregation.toUpperCase()}(CAST("${measure}" AS DOUBLE)) AS value\nFROM ${dataRef}\nGROUP BY "${String(roles.x || "time")}"\nORDER BY time_order;`,
      r: `# ATLAS Simple Forecast Preview\nchart_data <- aggregate(${measure} ~ ${String(roles.x || "time")}, data = df, FUN = ${aggregation})\nchart_data$moving_average <- stats::filter(chart_data$${measure}, rep(1/3, 3), sides = 1)\n`,
      sas: `/* ATLAS Simple Forecast data prep. Chart rendering is handled by ATLAS. */\nproc means data=work.${table} n mean sum median;\n    class ${String(roles.x || "time")};\n    var ${measure};\nrun;\n`,
    };
  }
  if (chartType === "survival") {
    return {
      python: `# ATLAS Basic Kaplan-Meier style survival preview\n# duration=${String(roles.duration || "duration")}; event=${String(roles.event || "event")}\n# Sort by duration, update survival *= (1 - events / at_risk) at each event time.\n`,
      sql: `-- ATLAS survival data prep\nSELECT "${String(roles.duration || "duration")}" AS duration, "${String(roles.event || "event")}" AS event_indicator, COUNT(*) AS records\nFROM ${dataRef}\nGROUP BY "${String(roles.duration || "duration")}", "${String(roles.event || "event")}"\nORDER BY duration;`,
      r: `# ATLAS Basic survival preview\n# For production survival analysis, use survival::survfit(Surv(${String(roles.duration || "duration")}, ${String(roles.event || "event")}) ~ 1, data=df)\n`,
      sas: `/* ATLAS survival data prep. Full survival modeling can use PROC LIFETEST in licensed SAS. */\nproc freq data=work.${table};\n    tables ${String(roles.duration || "duration")} * ${String(roles.event || "event")};\nrun;\n`,
    };
  }
  if (chartType === "data_profile" || chartType === "data_profile_matrix") {
    const vars = ((roles.numericVariables as string[]) || []).join(" ") || measure;
    return {
      python: `# ATLAS Data Profile\nprofile = df[[${((roles.numericVariables as string[]) || [measure]).map((v) => `"${v}"`).join(", ")}]].describe().T\nprofile["missing_pct"] = df[[${((roles.numericVariables as string[]) || [measure]).map((v) => `"${v}"`).join(", ")}]].isna().mean() * 100\nprint(profile)\n`,
      sql: `-- ATLAS Data Profile: use engine-specific summary statistics for selected variables.\nSELECT COUNT(*) AS rows FROM ${dataRef};`,
      r: `# ATLAS Data Profile\nsummary(df[, c(${((roles.numericVariables as string[]) || [measure]).map((v) => `"${v}"`).join(", ")})])\n`,
      sas: `/* ATLAS Data Profile */\nproc means data=work.${table} n nmiss mean median std min max;\n    var ${vars};\nrun;\n`,
    };
  }
  return {
    python: `# ATLAS Chart Studio - ${chartType}\n# Dataset: ${datasetName}\n# Version: ${versionId}\nimport pandas as pd\nimport matplotlib.pyplot as plt\n\n# df = pd.read_csv(\"${table}.csv\")\n${pythonBinning}chart_data = (\n    df.groupby(\"${category}\")[\"${measure}\"]\n      .${pandasAgg}()\n      .reset_index(name=\"${aggregation}_${measure}\")\n)\nchart_data = chart_data.sort_values(\"${aggregation}_${measure}\", ascending=False).head(${Number(roles.topN || 10)})\nax = chart_data.plot(kind=\"bar\", x=\"${category}\", y=\"${aggregation}_${measure}\", figsize=(10, 5), legend=False)\nax.set_title(\"${chartType.replace(/_/g, " ")} - ${datasetName}\")\nplt.tight_layout()\nplt.show()\n`,
    sql: `-- ATLAS Chart Studio data-prep query\n-- Dataset: ${datasetName}\n-- Version: ${versionId}\n${sqlBinning}SELECT\n  ${sqlCategoryExpr} AS category,\n  ${aggregation === "count" ? "COUNT(*)" : `${aggregation.toUpperCase()}(CAST("${measure}" AS DOUBLE))`} AS value,\n  COUNT(*) AS row_count\nFROM ${dataRef}\nGROUP BY ${sqlCategoryExpr}\nORDER BY value DESC\nLIMIT ${Number(roles.topN || 10)};`,
    r: `# ATLAS Chart Studio - ${chartType}\n# Dataset: ${datasetName}; Version: ${versionId}\n# If ggplot2 is available, uncomment the plotting lines.\n${rBinning}chart_data <- aggregate(${measure} ~ ${category}, data = df, FUN = ${aggregation === "count" ? "length" : aggregation})\nchart_data <- chart_data[order(-chart_data$${measure}), ]\n# library(ggplot2)\n# ggplot(head(chart_data, ${Number(roles.topN || 10)}), aes(x = reorder(${category}, ${measure}), y = ${measure})) +\n#   geom_col(fill = \"#2563eb\") + coord_flip() + theme_minimal()\n`,
    sas: `/* ATLAS Chart Studio SAS-compatible summary code */\n/* Dataset: ${datasetName}; Version: ${versionId} */\n/* Chart rendering is handled by ATLAS. This SAS-compatible code generates the chart data. */\n${sasBinning}proc means data=${sasTable} n sum mean median std min max;\n    class ${category};\n    var ${measure};\nrun;\n\nproc freq data=${sasTable};\n    tables ${category};\nrun;\n`,
  };
}

function inferNumericColumns(rows: ChartRow[], profile: DatasetProfile | null) {
  const profiled = profile?.schema.filter((column) => /int|float|double|numeric|number/i.test(column.dtype)).map((column) => column.name) ?? [];
  if (profiled.length) return profiled;
  const columns = Object.keys(rows[0] || {});
  return columns.filter((column) => rows.slice(0, 50).filter((row) => Number.isFinite(toNumber(row[column]))).length >= Math.max(3, Math.floor(Math.min(rows.length, 50) * 0.7)));
}

function aggregate(values: number[], method: string) {
  if (!values.length) return 0;
  if (method === "count") return values.length;
  if (method === "mean") return values.reduce((sum, value) => sum + value, 0) / values.length;
  if (method === "median") return quantile(values.slice().sort((a, b) => a - b), 0.5);
  return values.reduce((sum, value) => sum + value, 0);
}

function correlation(xs: number[], ys: number[]) {
  const pairs = xs.map((x, index) => [x, ys[index]]).filter(([x, y]) => Number.isFinite(x) && Number.isFinite(y));
  if (pairs.length < 2) return 0;
  const meanX = aggregate(pairs.map(([x]) => x), "mean");
  const meanY = aggregate(pairs.map(([, y]) => y), "mean");
  const numerator = pairs.reduce((sum, [x, y]) => sum + (x - meanX) * (y - meanY), 0);
  const denomX = Math.sqrt(pairs.reduce((sum, [x]) => sum + (x - meanX) ** 2, 0));
  const denomY = Math.sqrt(pairs.reduce((sum, [, y]) => sum + (y - meanY) ** 2, 0));
  return denomX && denomY ? numerator / (denomX * denomY) : 0;
}

function standardDeviation(values: number[]) {
  if (values.length < 2) return 0;
  const mean = aggregate(values, "mean");
  return Math.sqrt(values.reduce((sum, value) => sum + (value - mean) ** 2, 0) / (values.length - 1));
}

function quantile(sorted: number[], q: number) {
  if (!sorted.length) return 0;
  const pos = (sorted.length - 1) * q;
  const base = Math.floor(pos);
  const rest = pos - base;
  return sorted[base + 1] == null ? sorted[base] : sorted[base] + rest * (sorted[base + 1] - sorted[base]);
}

function extent(values: number[]): [number, number] {
  const finite = values.filter(Number.isFinite);
  if (!finite.length) return [0, 1];
  const min = Math.min(...finite);
  const max = Math.max(...finite);
  return min === max ? [min - 1, max + 1] : [min, max];
}

function scale(value: number, domainMin: number, domainMax: number, rangeMin: number, rangeMax: number) {
  return rangeMin + ((value - domainMin) / (domainMax - domainMin || 1)) * (rangeMax - rangeMin);
}

function toNumber(value: unknown) {
  const numeric = typeof value === "number" ? value : Number(String(value ?? "").replace(/[$,%]/g, ""));
  return Number.isFinite(numeric) ? numeric : 0;
}

function formatNumber(value: number) {
  if (Math.abs(value) >= 1000) return value.toLocaleString(undefined, { maximumFractionDigits: 0 });
  return value.toLocaleString(undefined, { maximumFractionDigits: 2 });
}

function truncate(value: string, max: number) {
  return value.length > max ? `${value.slice(0, max - 1)}...` : value;
}

function safeName(value: string) {
  return value.replace(/[^A-Za-z0-9_]+/g, "_").replace(/^_+|_+$/g, "") || "selected_dataset";
}

function downloadBlob(blob: Blob, filename: string) {
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = filename;
  document.body.appendChild(anchor);
  anchor.click();
  anchor.remove();
  URL.revokeObjectURL(url);
}
