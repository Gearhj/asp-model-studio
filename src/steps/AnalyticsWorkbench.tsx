import { useEffect, useMemo, useState } from "react";
import type React from "react";
import { Link } from "react-router-dom";
import { BarChart3, Brain, Code2, Copy, Database, FileText, Play, Save, Search, Sparkles, Trash2 } from "lucide-react";
import BrandLogo from "../components/BrandLogo";
import { CodeWorkspacePanel } from "../components/code/CodeWorkspacePanel";
import ExportResultActions from "../components/export/ExportResultActions";
import {
  getDataset,
  getDatasetAccess,
  getDatasetPreview,
  getDatasetProfile,
  listDatasets,
  type DatasetPreview,
  type DatasetProfile,
  type DatasetSummary,
  type DatasetVersionSummary,
} from "../lib/datasetLibrary";
import { auditAnalyticsRun, exportAnalyticsPackage, exportAnalyticsResultExcel, listAnalyticsInsights, runAnalyticsPreviewSql, saveAnalyticsInsight, type AnalyticsExportFormat, type AnalyticsSqlRunResult, type AtlasAnalyticsInsight } from "../lib/analyticsWorkbench";
import {
  cleanupQuestion as cleanupQuestionText,
  fetchPythonDiagnostics,
  fetchSasDiagnostics,
  runUserPython,
  runUserR,
  runUserSas,
  runUserSasCompatible,
  saveSasRuntimeSettings,
  testSasConnection,
  type CodeRunResult,
  type CodeLanguage,
  type PythonDiagnostics,
  type PythonExecutionResult,
  type SasDiagnostics,
  type SasExecutionMode,
} from "../lib/codeExecution";
import { useWorkflowStore } from "../state/useWorkflowStore";

const API_BASE = (import.meta.env.VITE_API_BASE as string | undefined)?.replace(/\/$/, "") || "http://127.0.0.1:8001/api";

type NumericSummary = {
  count: number;
  mean: number;
  median: number;
  std: number;
  min: number;
  max: number;
  p5: number;
  p25: number;
  p50: number;
  p75: number;
  p95: number;
  missingPct: number;
  distinct: number;
};

type PivotConfig = {
  rowField: string;
  columnField: string;
  valueField: string;
  aggregation: string;
  autoBinRows: boolean;
  autoBinColumns: boolean;
  topN: number;
  binaryTarget: string;
};

type PivotResult = {
  config: PivotConfig;
  columns: string[];
  rows: Array<Record<string, string | number>>;
  readout: string;
};

export default function AnalyticsWorkbench() {
  const projectId = useWorkflowStore((state) => state.projectId);
  const [datasets, setDatasets] = useState<DatasetSummary[]>([]);
  const [datasetId, setDatasetId] = useState("");
  const [dataset, setDataset] = useState<(DatasetSummary & { versions?: DatasetVersionSummary[] }) | null>(null);
  const [versionId, setVersionId] = useState("");
  const [profile, setProfile] = useState<DatasetProfile | null>(null);
  const [preview, setPreview] = useState<DatasetPreview | null>(null);
  const [accessLevel, setAccessLevel] = useState("viewer");
  const [businessQuestion, setBusinessQuestion] = useState("");
  const [savedQuestionAt, setSavedQuestionAt] = useState("");
  const [analysisPlan, setAnalysisPlan] = useState<string[]>([]);
  const [target, setTarget] = useState("");
  const [selectedColumn, setSelectedColumn] = useState("");
  const [groupColumn, setGroupColumn] = useState("");
  const [metricColumn, setMetricColumn] = useState("");
  const [aggregation, setAggregation] = useState("mean");
  const [secondaryDatasetId, setSecondaryDatasetId] = useState("");
  const [secondaryDataset, setSecondaryDataset] = useState<(DatasetSummary & { versions?: DatasetVersionSummary[] }) | null>(null);
  const [secondaryVersionId, setSecondaryVersionId] = useState("");
  const [secondaryPreview, setSecondaryPreview] = useState<DatasetPreview | null>(null);
  const [joinKey, setJoinKey] = useState("");
  const [joinType, setJoinType] = useState("left");
  const [insights, setInsights] = useState<AtlasAnalyticsInsight[]>([]);
  const [assistantText, setAssistantText] = useState("Select a dataset and enter a business question to generate ATLAS takeaways.");
  const [message, setMessage] = useState("");
  const [userPython, setUserPython] = useState('print("ATLAS Analytics Workbench Python smoke test passed.")\nprint(df.shape)\nprint(df.head())');
  const [userSql, setUserSql] = useState("");
  const [userR, setUserR] = useState('cat("ATLAS R smoke test passed.\\n")\ncat("Rows:", nrow(df), " Columns:", ncol(df), "\\n")\nprint(head(df))');
  const [userSas, setUserSas] = useState("");
  const [activeCodeLanguage, setActiveCodeLanguage] = useState<CodeLanguage>("python");
  const [insightFilter, setInsightFilter] = useState("all");
  const [pythonOutput, setPythonOutput] = useState<PythonExecutionResult | null>(null);
  const [pythonDiagnostics, setPythonDiagnostics] = useState<PythonDiagnostics | null>(null);
  const [sasDiagnostics, setSasDiagnostics] = useState<SasDiagnostics | null>(null);
  const [sasMode, setSasMode] = useState<SasExecutionMode>("template_only");
  const [sasCfgname, setSasCfgname] = useState("");
  const [sasCfgfile, setSasCfgfile] = useState("");
  const [savingSasSettings, setSavingSasSettings] = useState(false);
  const [testingSasConnection, setTestingSasConnection] = useState(false);
  const [runningPython, setRunningPython] = useState(false);
  const [sqlResult, setSqlResult] = useState<AnalyticsSqlRunResult | null>(null);
  const [rResult, setRResult] = useState<CodeRunResult | null>(null);
  const [sasResult, setSasResult] = useState<CodeRunResult | null>(null);
  const [runningSql, setRunningSql] = useState(false);
  const [runningR, setRunningR] = useState(false);
  const [runningSas, setRunningSas] = useState(false);
  const [pivotRowField, setPivotRowField] = useState("");
  const [pivotColumnField, setPivotColumnField] = useState("");
  const [pivotValueField, setPivotValueField] = useState("");
  const [pivotAggregation, setPivotAggregation] = useState("mean");
  const [pivotAutoBinRows, setPivotAutoBinRows] = useState(true);
  const [pivotAutoBinColumns, setPivotAutoBinColumns] = useState(false);
  const [pivotTopN, setPivotTopN] = useState(12);

  useEffect(() => {
    listDatasets()
      .then((payload) => {
        setDatasets(payload.datasets);
        if (!datasetId && payload.datasets[0]) setDatasetId(payload.datasets[0].datasetId);
      })
      .catch((error) => setMessage(error instanceof Error ? error.message : "ATLAS could not load accessible datasets."));
    fetchPythonDiagnostics().then(setPythonDiagnostics).catch(() => undefined);
    refreshSasDiagnostics().catch(() => undefined);
  }, []);

  async function refreshSasDiagnostics() {
    const diagnostics = await fetchSasDiagnostics();
    setSasDiagnostics(diagnostics);
    setSasMode(diagnostics.settings?.executionMode ?? diagnostics.sasExecutionMode ?? "template_only");
    setSasCfgname(diagnostics.settings?.cfgname ?? diagnostics.activeCfgName ?? "");
    setSasCfgfile(diagnostics.settings?.cfgfile ?? diagnostics.activeCfgFile ?? "");
    return diagnostics;
  }

  useEffect(() => {
    if (!datasetId) return;
    let alive = true;
    async function loadDataset() {
      try {
        const loaded = await getDataset(datasetId);
        if (!alive) return;
        const version = loaded.versions?.[loaded.versions.length - 1]?.versionId || loaded.latestVersion?.versionId || "";
        setDataset(loaded);
        setVersionId(version);
        const access = await getDatasetAccess(datasetId).catch(() => ({ access: [] }));
        const explicit = access.access.find((entry) => (entry.user_id ?? entry.userId) === loaded.ownerUserId) ?? access.access[0];
        setAccessLevel(explicit?.role || "viewer");
        if (version) await loadPrimaryVersion(datasetId, version, alive);
        const insightPayload = await listAnalyticsInsights({ datasetId });
        if (alive) setInsights(insightPayload.insights);
        await auditAnalyticsRun({ datasetId, versionId: version, analysisType: "workspace_opened" }).catch(() => undefined);
      } catch (error) {
        if (alive) setMessage(error instanceof Error ? error.message : "ATLAS could not load this dataset for analytics.");
      }
    }
    loadDataset();
    return () => {
      alive = false;
    };
  }, [datasetId]);

  async function loadPrimaryVersion(nextDatasetId: string, nextVersionId: string, alive = true) {
    const profilePayload = await getDatasetProfile(nextDatasetId, nextVersionId);
    const previewPayload = await getDatasetPreview(nextDatasetId, nextVersionId);
    if (!alive) return;
    setProfile(profilePayload.profile);
    setPreview(previewPayload);
    setSelectedColumn(profilePayload.profile?.schema?.[0]?.name ?? previewPayload.columns[0] ?? "");
    const firstNumeric = profilePayload.profile?.schema?.find((col) => isNumericColumn(previewPayload.rows, col.name))?.name ?? "";
    setMetricColumn(firstNumeric);
    setPivotValueField(firstNumeric);
    setPivotRowField(firstNumeric || previewPayload.columns[0] || "");
    setGroupColumn(profilePayload.profile?.schema?.find((col) => !isNumericColumn(previewPayload.rows, col.name))?.name ?? previewPayload.columns[0] ?? "");
    setTarget(profilePayload.profile?.targetCandidates?.[0] ?? "");
  }

  useEffect(() => {
    if (!secondaryDatasetId) {
      setSecondaryDataset(null);
      setSecondaryVersionId("");
      setSecondaryPreview(null);
      return;
    }
    let alive = true;
    async function loadSecondary() {
      try {
        const loaded = await getDataset(secondaryDatasetId);
        const version = loaded.versions?.[loaded.versions.length - 1]?.versionId || loaded.latestVersion?.versionId || "";
        const previewPayload = version ? await getDatasetPreview(secondaryDatasetId, version) : null;
        if (!alive) return;
        setSecondaryDataset(loaded);
        setSecondaryVersionId(version);
        setSecondaryPreview(previewPayload);
        const common = preview?.columns?.find((column) => previewPayload?.columns?.includes(column));
        setJoinKey(common ?? "");
      } catch (error) {
        if (alive) setMessage(error instanceof Error ? error.message : "ATLAS could not load the secondary dataset.");
      }
    }
    loadSecondary();
    return () => {
      alive = false;
    };
  }, [secondaryDatasetId, preview?.columns?.join("|")]);

  const rows = preview?.rows ?? [];
  const columns = preview?.columns ?? [];
  const secondaryRows = secondaryPreview?.rows ?? [];
  const numericColumns = useMemo(() => columns.filter((column) => isNumericColumn(rows, column)), [columns, rows]);
  const categoricalColumns = useMemo(() => columns.filter((column) => !numericColumns.includes(column)), [columns, numericColumns]);
  const selectedSummary = useMemo(() => summarizeColumn(rows, selectedColumn), [rows, selectedColumn]);
  const targetSummary = useMemo(() => buildTargetSummary(rows, target, numericColumns, categoricalColumns), [rows, target, numericColumns, categoricalColumns]);
  const groupRows = useMemo(() => groupComparison(rows, groupColumn, metricColumn, aggregation, target), [rows, groupColumn, metricColumn, aggregation, target]);
  const correlations = useMemo(() => topCorrelations(rows, numericColumns), [rows, numericColumns]);
  const quality = useMemo(() => qualityReview(profile, rows, columns, numericColumns), [profile, rows, columns, numericColumns]);
  const pivot = useMemo(() => buildPivot(rows, { rowField: pivotRowField, columnField: pivotColumnField, valueField: pivotValueField, aggregation: pivotAggregation, autoBinRows: pivotAutoBinRows, autoBinColumns: pivotAutoBinColumns, topN: pivotTopN, binaryTarget: target }), [rows, pivotRowField, pivotColumnField, pivotValueField, pivotAggregation, pivotAutoBinRows, pivotAutoBinColumns, pivotTopN, target]);
  const codeContext = { dataset, versionId, profile, rows, columns, target, groupColumn, metricColumn, secondaryDataset, secondaryVersionId, secondaryPreview, joinKey, joinType, pivot, businessQuestion };
  const generatedPython = useMemo(() => buildPythonTemplate(codeContext), [dataset, versionId, rows, columns, target, groupColumn, metricColumn, secondaryDataset, secondaryVersionId, joinKey, joinType, pivot, businessQuestion]);
  const generatedSql = useMemo(() => buildSqlTemplate(codeContext), [dataset, versionId, profile, columns, target, secondaryDataset, secondaryVersionId, secondaryPreview, joinKey, joinType, pivot, businessQuestion]);
  const generatedR = useMemo(() => buildRTemplate(codeContext), [dataset, versionId, columns, target, secondaryDataset, secondaryVersionId, joinKey, joinType, pivot, businessQuestion]);
  const generatedSas = useMemo(() => buildSasTemplate(codeContext), [dataset, versionId, columns, target, secondaryDataset, secondaryVersionId, joinKey, joinType, pivot, businessQuestion]);
  const recommendedAnalyses = useMemo(() => recommendAnalyses(businessQuestion, target, targetSummary.mode, columns), [businessQuestion, target, targetSummary.mode, columns]);
  const languageCode = {
    python: { label: "Python", generated: generatedPython, user: userPython, setUser: setUserPython },
    sql: { label: "SQL", generated: generatedSql, user: userSql, setUser: setUserSql },
    r: { label: "R", generated: generatedR, user: userR, setUser: setUserR },
    sas: { label: "SAS-compatible", generated: generatedSas, user: userSas, setUser: setUserSas },
  } satisfies Record<CodeLanguage, { label: string; generated: string; user: string; setUser: (value: string) => void }>;
  const activeLanguageCode = languageCode[activeCodeLanguage];
  const filteredInsights = useMemo(() => filterInsights(insights, insightFilter), [insights, insightFilter]);
  const activeExecutionResult = activeCodeLanguage === "python" ? pythonOutput : activeCodeLanguage === "sql" ? sqlResult : activeCodeLanguage === "r" ? rResult : sasResult;
  const datasetName = dataset?.name ?? datasetId;
  const moduleExportMetadata = {
    datasetId,
    linkedProjectId: projectId,
    target,
    previewRowCount: rows.length,
    profileRows: profile?.rowCount ?? dataset?.latestVersion?.rowCount ?? rows.length,
    profileColumns: profile?.columnCount ?? columns.length,
  };

  const currentExportPayload = (savedInsight?: AtlasAnalyticsInsight) => buildExportPayload({
    businessQuestion,
    cleanedQuestion: businessQuestion,
    analysisPlan,
    generatedPython,
    generatedSql,
    generatedR,
    generatedSas,
    userPython,
    userSql,
    userR,
    userSas,
    activeLanguage: activeCodeLanguage,
    activeCode: activeLanguageCode.user || activeLanguageCode.generated,
    dataset,
    datasetId,
    versionId,
    projectId,
    target,
    previewRowCount: rows.length,
    pivot,
    sqlResult,
    sasResult,
    pythonResult: pythonOutput,
    rResult,
    savedInsight,
    metadata: {
      profileRows: profile?.rowCount ?? dataset?.latestVersion?.rowCount ?? rows.length,
      profileColumns: profile?.columnCount ?? columns.length,
      selectedColumn,
      groupColumn,
      metricColumn,
      aggregation,
      secondaryDatasetId,
      secondaryDatasetName: secondaryDataset?.name ?? "",
      secondaryVersionId,
      joinKey,
      joinType,
      recommendedAnalyses,
      qualityFindings: quality.slice(0, 10).map((item) => item.label),
    },
  });

  const downloadExport = async (format: AnalyticsExportFormat, savedInsight?: AtlasAnalyticsInsight) => {
    try {
      const { blob, filename } = await exportAnalyticsPackage(format, currentExportPayload(savedInsight));
      downloadBlob(blob, filename);
      const label = format === "excel" ? "Excel" : format === "word" ? "Word" : "PowerPoint";
      setMessage(`${label} export created.`);
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "ATLAS could not create this analytics export.");
    }
  };

  const downloadResultExport = async (_format: AnalyticsExportFormat, resultType: string, resultPayload: Record<string, unknown>) => {
    try {
      const { blob, filename } = await exportAnalyticsResultExcel({
        resultType: resultType as never,
        exportTitle: resultExportTitle(resultType),
        datasetName,
        versionId,
        businessQuestion,
        resultPayload,
        metadata: moduleExportMetadata,
        createdAt: new Date().toISOString(),
      });
      downloadBlob(blob, filename);
      setMessage(`${resultExportTitle(resultType)} Excel export created.`);
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "ATLAS could not create this Excel result export.");
    }
  };

  const columnExplorerExportPayload = () => ({
    selectedColumn,
    statistics: selectedSummary.kind === "numeric" ? numericSummaryRows(selectedSummary.summary) : [["Column", selectedColumn], ["Type", "Categorical"], ["Distinct preview values", counts(rows, selectedColumn).length]],
    histogramBins: selectedSummary.kind === "numeric" ? histogramBins(numericValues(rows, selectedColumn)) : counts(rows, selectedColumn).map(([label, value]) => ({ category: label, count: value })),
    missingness: selectedSummary.kind === "numeric" ? selectedSummary.summary.missingPct : rows.length ? rows.filter((row) => row[selectedColumn] === null || row[selectedColumn] === undefined || row[selectedColumn] === "").length / rows.length : 0,
    distinctCount: new Set(rows.map((row) => row[selectedColumn])).size,
    warnings: quality.filter((item) => item.label.includes(selectedColumn)).map((item) => item.detail),
  });

  const targetRelationshipExportPayload = () => ({
    target,
    summary: [["Mode", targetSummary.mode], ["Summary", targetSummary.text]],
    ranking: targetSummary.rankings.map((row) => ({ feature: row.feature, score: row.value })),
  });

  const groupComparisonExportPayload = () => ({
    configuration: [["Group field", groupColumn], ["Measure field", metricColumn], ["Aggregation", aggregation], ["Target", target || "-"]],
    rows: groupRows,
    chartData: groupRows.map((row) => ({ group: row.group, value: row.value })),
  });

  const dataQualityExportPayload = () => ({
    qualityChecks: quality,
    correlations,
    warnings: quality.filter((item) => item.status !== "pass").map((item) => `${item.label}: ${item.detail}`),
  });

  const pivotExportPayload = () => ({
    configuration: Object.entries(pivot.config),
    rows: pivot.rows,
    readout: pivot.readout,
    chartData: pivotChartRows(pivot),
  });

  const codeResultExportPayload = () => {
    if (activeCodeLanguage === "sql") {
      return {
        rows: sqlResult?.rows ?? [],
        execution: [["Status", sqlResult?.status ?? "not run"], ["Rows", sqlResult?.rowCount ?? 0], ["Runtime ms", sqlResult?.runtimeMs ?? 0], ["Error", sqlResult?.error ?? ""]],
      };
    }
    if (activeCodeLanguage === "sas") {
      const result = sasResult as ({ stdout?: string; stderr?: string; tables?: Array<{ title?: string; name?: string; rows?: Array<Record<string, unknown>> }>; unsupportedStatements?: string[]; translatedPython?: string } | null);
      return {
        tables: result?.tables ?? [],
        stdout: result?.stdout ?? "",
        stderr: result?.stderr ?? "",
        translatedPython: result?.translatedPython ?? "",
        unsupportedStatements: result?.unsupportedStatements ?? [],
      };
    }
    const result = (activeCodeLanguage === "python" ? pythonOutput : rResult) as ({ status?: string; runtimeMs?: number; returnCode?: number; stdout?: string; stderr?: string; tables?: Array<Record<string, unknown>> } | null);
    return {
      execution: [["Status", result?.status ?? "not run"], ["Runtime ms", result?.runtimeMs ?? 0], ["Return code", (result as { returnCode?: number } | null)?.returnCode ?? ""]],
      stdout: result?.stdout ?? "",
      stderr: result?.stderr ?? "",
      tables: (result as { tables?: Array<Record<string, unknown>> } | null)?.tables ?? [],
    };
  };

  const useGeneratedCode = (language: CodeLanguage) => {
    const config = languageCode[language];
    config.setUser(config.generated);
    setActiveCodeLanguage(language);
    setMessage(`${config.label} generated code loaded into the user-edited code workspace.`);
  };

  const saveBusinessQuestion = async () => {
    if (!datasetId || !versionId || !businessQuestion.trim()) {
      setMessage("Enter a business question and select a dataset before saving.");
      return;
    }
    const timestamp = new Date().toISOString();
    try {
      const insight = await saveAnalyticsInsight({
        title: `Business question: ${businessQuestion.slice(0, 72)}`,
        summary: businessQuestion.trim(),
        datasetId,
        versionId,
        projectId,
        businessQuestion,
        analysisType: "business_question",
        evidence: {
          chartType: "question_record",
          columnsUsed: [target].filter(Boolean),
          metrics: { savedAt: timestamp, datasetName: dataset?.name ?? datasetId },
        },
      });
      setSavedQuestionAt(timestamp);
      setInsights((current) => [insight, ...current]);
      setMessage("Business question saved to the analytics workspace.");
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "ATLAS could not save the business question.");
    }
  };

  const cleanupQuestion = async () => {
    if (!businessQuestion.trim()) {
      setMessage("Enter rough question language before cleanup.");
      return;
    }
    let cleaned = "";
    let source: "llm" | "deterministic" = "deterministic";
    try {
      const result = await cleanupQuestionText({
        text: businessQuestion,
        context: {
          datasetName: dataset?.name ?? "",
          targetColumn: target || columns[0] || "the selected target",
          columns,
          businessQuestion,
        },
      });
      cleaned = result.cleanedText;
      source = result.source;
    } catch {
      cleaned = deterministicQuestionCleanup(businessQuestion, target || columns[0] || "the selected target");
    }
    if (businessQuestion.trim() && cleaned !== businessQuestion && !window.confirm("Replace the current question with the cleaned ATLAS draft?")) return;
    setBusinessQuestion(cleaned);
    setMessage(source === "llm" ? "Question cleaned up using the configured ATLAS LLM endpoint." : "Question cleaned up using deterministic ATLAS cleanup.");
  };

  const generatePlan = () => {
    const plan = buildAnalysisPlan({ question: businessQuestion, datasetName: dataset?.name ?? "selected dataset", target, numericColumns, categoricalColumns, hasSecondary: !!secondaryDatasetId });
    setAnalysisPlan(plan);
    setAssistantText(`ATLAS generated a ${plan.length}-step analysis plan tied to ${dataset?.name ?? "the selected dataset"}.`);
    auditAnalyticsRun({ datasetId, versionId, analysisType: "analysis_plan_generated" }).catch(() => undefined);
  };

  const keyTakeaways = () => {
    const parts = [
      `${dataset?.name ?? "The selected dataset"} has ${(profile?.rowCount ?? dataset?.latestVersion?.rowCount ?? rows.length).toLocaleString()} rows and ${(profile?.columnCount ?? columns.length).toLocaleString()} columns.`,
      `${numericColumns.length} numeric columns and ${categoricalColumns.length} categorical/date-like columns are available in the preview/profile.`,
      quality.length ? `Primary data quality watch item: ${quality[0].label}.` : "No major data quality warnings were detected in the preview/profile.",
      target ? `Target analysis is focused on ${target}.` : "Select a target variable to unlock target relationship analysis.",
      correlations.length ? `Strongest numeric relationship in preview: ${correlations[0].a} and ${correlations[0].b} (${correlations[0].corr.toFixed(2)}).` : "Correlation analysis needs at least two numeric fields.",
    ];
    setAssistantText(parts.join(" "));
  };

  const saveInsight = async (analysisType = "workbench_summary") => {
    if (!datasetId || !versionId) return;
    try {
      const insight = await saveAnalyticsInsight({
        title: businessQuestion ? businessQuestion.slice(0, 90) : `Analytics summary for ${dataset?.name ?? "dataset"}`,
        summary: assistantText,
        datasetId,
        versionId,
        projectId,
        businessQuestion,
        analysisType,
        evidence: {
          chartType: "analytics_workbench",
          columnsUsed: [selectedColumn, target, groupColumn, metricColumn, joinKey].filter(Boolean),
          filters: {
            primaryDatasetId: datasetId,
            primaryVersionId: versionId,
            secondaryDatasetId: secondaryDatasetId || undefined,
            secondaryVersionId: secondaryVersionId || undefined,
            joinType: secondaryDatasetId ? joinType : undefined,
          },
          metrics: {
            rows: profile?.rowCount ?? rows.length,
            columns: profile?.columnCount ?? columns.length,
            numericColumns: numericColumns.length,
            categoricalColumns: categoricalColumns.length,
            qualityFindings: quality.length,
            analysisPlan,
            pivotConfig: pivot.config,
            pivotPreview: pivot.rows.slice(0, 20),
            pivotReadout: pivot.readout,
            generatedPython,
            generatedSql,
            generatedR,
            generatedSas,
            userEditedPython: userPython,
            userEditedSql: userSql,
            userEditedR: userR,
            userEditedSas: userSas,
            activeLanguage: activeCodeLanguage,
            activeCode: activeLanguageCode.user || activeLanguageCode.generated,
          },
        },
      });
      setInsights((current) => [insight, ...current]);
      setMessage("Insight saved to the analytics store.");
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "ATLAS could not save this insight.");
    }
  };

  const savePivotInsight = async () => {
    setAssistantText(pivot.readout);
    await saveInsight("pivot_table");
  };

  const runSqlOnPreview = async () => {
    setRunningSql(true);
    setSqlResult(null);
    try {
      const result = await runAnalyticsPreviewSql({
        sql: userSql || generatedSql,
        datasetName: dataset?.name ?? "primary_dataset",
        versionId,
        previewRows: rows,
        secondaryDatasetName: secondaryDataset?.name,
        secondaryPreviewRows: secondaryRows,
      });
      setSqlResult(result);
      await auditAnalyticsRun({ datasetId, versionId, analysisType: result.status === "success" ? "sql_preview_run" : "sql_preview_blocked" }).catch(() => undefined);
    } catch (error) {
      setSqlResult({
        status: "error",
        columns: [],
        rows: [],
        rowCount: 0,
        runtimeMs: 0,
        error: error instanceof Error ? error.message : "ATLAS could not run this SQL against preview rows.",
      });
    } finally {
      setRunningSql(false);
    }
  };

  const runPython = async () => {
    setRunningPython(true);
    setPythonOutput(null);
    try {
      const payload = await runUserPython({
        code: userPython,
        projectId,
        workflowStep: "analytics",
        context: {
          preview_rows: rows,
          primary_preview_rows: rows,
          secondary_preview_rows: secondaryRows,
          dataset_name: dataset?.name ?? "",
          dataset_id: datasetId,
          version_id: versionId,
        },
      });
      if (!payload.ok) {
        const diagnostics = await fetchPythonDiagnostics().catch(() => null);
        if (diagnostics) {
          setPythonDiagnostics(diagnostics);
          payload.diagnostics = diagnostics;
        }
      }
      setPythonOutput(payload);
      await auditAnalyticsRun({ datasetId, versionId, analysisType: "python_run" }).catch(() => undefined);
    } catch {
      setPythonOutput({ ok: false, status: "unavailable", stdout: "", stderr: "Python execution backend is unavailable. Code will still be included in notebook export.", runtimeMs: 0 });
    } finally {
      setRunningPython(false);
    }
  };

  const codeContextPayload = () => ({
    datasetName: dataset?.name ?? "",
    versionId,
    previewRows: rows,
    businessQuestion,
    targetColumn: target,
  });

  const refreshRuntimeDiagnostics = async () => {
    try {
      const diagnostics = await fetchPythonDiagnostics();
      setPythonDiagnostics(diagnostics);
      await refreshSasDiagnostics().catch(() => undefined);
      setMessage("Runtime diagnostics refreshed.");
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "ATLAS could not refresh runtime diagnostics.");
    }
  };

  const runRCode = async () => {
    if (!pythonDiagnostics?.rExecutionAvailable) {
      setRResult({
        ok: false,
        status: "unavailable",
        stdout: "",
        stderr: "R execution is not configured on this machine. Install R and ensure Rscript is on PATH to enable local R execution.",
        runtimeMs: 0,
      });
      return;
    }
    setRunningR(true);
    setRResult(null);
    try {
      const result = await runUserR({ code: userR || generatedR, context: codeContextPayload() });
      setRResult(result);
    } finally {
      setRunningR(false);
    }
  };

  const runSasCompatibleCode = async () => {
    setRunningSas(true);
    setSasResult(null);
    try {
      const result = await runUserSasCompatible({ code: userSas || generatedSas, context: codeContextPayload() });
      setSasResult(result);
    } finally {
      setRunningSas(false);
    }
  };

  const saveSasSettings = async (override?: { executionMode: SasExecutionMode; cfgname?: string; cfgfile?: string }) => {
    setSavingSasSettings(true);
    setMessage("");
    try {
      const payload = await saveSasRuntimeSettings({
        executionMode: override?.executionMode ?? sasMode,
        cfgname: override?.cfgname ?? sasCfgname,
        cfgfile: override?.cfgfile ?? sasCfgfile,
      });
      if (!payload.ok) {
        setMessage(payload.detail || "ATLAS could not save SAS runtime settings.");
        return;
      }
      if (payload.diagnostics) {
        setSasDiagnostics(payload.diagnostics);
        setSasMode(payload.diagnostics.settings?.executionMode ?? payload.diagnostics.sasExecutionMode ?? "template_only");
        setSasCfgname(payload.diagnostics.settings?.cfgname ?? payload.diagnostics.activeCfgName ?? "");
        setSasCfgfile(payload.diagnostics.settings?.cfgfile ?? payload.diagnostics.activeCfgFile ?? "");
      } else {
        await refreshSasDiagnostics();
      }
      const diagnostics = await fetchPythonDiagnostics().catch(() => null);
      if (diagnostics) setPythonDiagnostics(diagnostics);
      setMessage("SAS runtime settings saved.");
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "ATLAS could not save SAS runtime settings.");
    } finally {
      setSavingSasSettings(false);
    }
  };

  const resetSasTemplateOnly = async () => {
    setSasMode("template_only");
    setSasCfgname("");
    setSasCfgfile("");
    await saveSasSettings({ executionMode: "template_only", cfgname: "", cfgfile: "" });
  };

  const runSasConnectionTest = async () => {
    setTestingSasConnection(true);
    setSasResult(null);
    setMessage("");
    try {
      const result = await testSasConnection();
      setSasResult(result);
      await refreshSasDiagnostics();
      const diagnostics = await fetchPythonDiagnostics().catch(() => null);
      if (diagnostics) setPythonDiagnostics(diagnostics);
      setMessage(result.ok && result.status === "success" ? "SAS connection test succeeded." : "SAS connection test completed. Review the result panel for details.");
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "ATLAS could not test the SAS connection.");
    } finally {
      setTestingSasConnection(false);
    }
  };

  const saveCodeInsight = async (language: "python" | "sql" | "r" | "sas", code: string) => {
    const config = languageCode[language];
    const title = `${config.label} code snippet: ${dataset?.name ?? "dataset"}`;
    const createdAt = new Date().toISOString();
    try {
      const insight = await saveAnalyticsInsight({
        title,
        summary: `Saved ${config.label} code generated from the ATLAS Analytics Workbench context.`,
        datasetId,
        versionId,
        projectId,
        businessQuestion,
        analysisType: `${language}_code_snippet`,
        evidence: {
          chartType: "code_workspace",
          columnsUsed: [target, pivot.config.rowField, pivot.config.columnField, pivot.config.valueField].filter(Boolean),
          metrics: {
            language,
            languageLabel: config.label,
            datasetName: dataset?.name ?? datasetId,
            versionId,
            code,
            activeLanguage: language,
            activeCode: code,
            generatedCode: config.generated,
            userEditedCode: config.user,
            generatedPython,
            generatedSql,
            generatedR,
            generatedSas,
            pivotConfig: pivot.config,
            activeAnalysisContext: {
              target,
              selectedColumn,
              groupColumn,
              metricColumn,
              aggregation,
              secondaryDatasetId,
              secondaryVersionId,
              joinKey,
              joinType,
            },
            secondaryDatasetId,
            createdAt,
            createdBy: "local_user",
            linkedProjectId: projectId,
          },
        },
      });
      setInsights((current) => [insight, ...current]);
      setMessage(`${config.label} code snippet saved as an insight.`);
    } catch (error) {
      setMessage(error instanceof Error ? error.message : `ATLAS could not save the ${config.label} code snippet.`);
    }
  };

  const refreshVersion = async (nextVersionId: string) => {
    setVersionId(nextVersionId);
    if (!datasetId || !nextVersionId) return;
    try {
      await loadPrimaryVersion(datasetId, nextVersionId);
      await auditAnalyticsRun({ datasetId, versionId: nextVersionId, analysisType: "dataset_selected" }).catch(() => undefined);
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "ATLAS could not refresh this dataset version.");
    }
  };

  return (
    <div className="w-full space-y-5">
      <section className="overflow-hidden rounded-2xl border border-slate-200 bg-white shadow-sm">
        <div className="border-b border-slate-200 bg-gradient-to-r from-slate-950 via-slate-900 to-blue-950 p-5 text-white">
          <BrandLogo size="md" variant="dark" showSubtitle className="mb-4" />
          <div className="flex flex-col gap-4 xl:flex-row xl:items-end xl:justify-between">
            <div>
              <div className="flex items-center gap-2">
                <BarChart3 size={24} className="text-sky-300" />
                <h1 className="text-2xl font-semibold">Analytics Workbench</h1>
              </div>
              <p className="mt-2 max-w-3xl text-sm leading-6 text-slate-200">
                A governed analytical sandbox for asking a business question, exploring accessible datasets, drafting Python and SQL, and saving reusable findings.
              </p>
            </div>
            <div className="grid gap-2 text-xs sm:grid-cols-3">
              <StatusPill label="Dataset" value={dataset?.name ?? "Not selected"} />
              <StatusPill label="Question" value={savedQuestionAt ? "Saved" : businessQuestion ? "Draft" : "Not started"} />
              <StatusPill label="Access" value={accessLevel} />
            </div>
          </div>
        </div>
        <div className="flex flex-wrap gap-2 bg-slate-50 px-5 py-3 text-xs font-semibold text-slate-600">
          {["Question", "Data", "Analyze", "Code", "Insights"].map((label) => (
            <a key={label} href={`#${label.toLowerCase()}`} className="rounded-full border border-slate-200 bg-white px-3 py-1.5 hover:border-blue-300 hover:text-blue-700">
              {label}
            </a>
          ))}
          <Link to="/datasets" className="ml-auto rounded-full border border-slate-200 bg-white px-3 py-1.5 hover:border-blue-300 hover:text-blue-700">
            Dataset Library
          </Link>
        </div>
        {message && <div className="mx-5 my-4 rounded-lg border border-blue-200 bg-blue-50 px-3 py-2 text-sm text-blue-900">{message}</div>}
      </section>

      <section className="grid gap-5 xl:grid-cols-[minmax(0,1fr)_360px]">
        <main className="min-w-0 space-y-5">
          <WorkbenchSection id="question" title="Question and Analysis Plan" tone="blue">
            <div className="grid gap-4 xl:grid-cols-[1fr_330px]">
              <div>
                <label className="text-xs font-semibold uppercase tracking-wide text-slate-500">Business Question</label>
                <textarea
                  className="mt-2 min-h-[120px] w-full rounded-xl border border-slate-300 bg-white p-3 text-sm outline-none focus:border-blue-400 focus:ring-2 focus:ring-blue-100"
                  value={businessQuestion}
                  onChange={(event) => setBusinessQuestion(event.target.value)}
                  placeholder="Example: Which housing-area characteristics are most strongly associated with median home value?"
                />
                <div className="mt-3 flex flex-wrap gap-2">
                  <ActionButton onClick={saveBusinessQuestion} label="Save Business Question" icon={<Save size={15} />} />
                  <ActionButton onClick={cleanupQuestion} label="Clean Up Question" icon={<Sparkles size={15} />} variant="secondary" />
                  <ActionButton onClick={generatePlan} label="Generate Analysis Plan" icon={<Brain size={15} />} variant="secondary" />
                  <ActionButton onClick={() => { setBusinessQuestion(""); setAnalysisPlan([]); setSavedQuestionAt(""); }} label="Clear" icon={<Trash2 size={15} />} variant="ghost" />
                </div>
                <p className="mt-2 text-xs text-slate-500">
                  Uses deterministic ATLAS cleanup in this local build. Connect `ATLAS_LLM_ENDPOINT` to enable LLM rewrite.
                </p>
              </div>
              <div className="rounded-xl border border-blue-200 bg-blue-50 p-4">
                <div className="text-xs font-semibold uppercase tracking-wide text-blue-700">Recommended Analysis Plan</div>
                {analysisPlan.length ? (
                  <ol className="mt-3 list-decimal space-y-2 pl-5 text-sm leading-6 text-blue-950">
                    {analysisPlan.map((step) => <li key={step}>{step}</li>)}
                  </ol>
                ) : (
                  <p className="mt-3 text-sm leading-6 text-blue-900">Enter a business question and click Generate Analysis Plan.</p>
                )}
              </div>
            </div>
          </WorkbenchSection>

          <WorkbenchSection id="data" title="Dataset Context" tone="slate">
            <div className="grid gap-3 lg:grid-cols-[1fr_230px]">
              <label className="grid gap-1 text-xs font-semibold uppercase tracking-wide text-slate-500">
                Primary Dataset
                <select className="rounded-lg border border-slate-300 px-3 py-2 text-sm font-normal normal-case text-slate-900" value={datasetId} onChange={(event) => setDatasetId(event.target.value)}>
                  {datasets.map((item) => <option key={item.datasetId} value={item.datasetId}>{item.name}</option>)}
                </select>
              </label>
              <label className="grid gap-1 text-xs font-semibold uppercase tracking-wide text-slate-500">
                Dataset Version
                <select className="rounded-lg border border-slate-300 px-3 py-2 text-sm font-normal normal-case text-slate-900" value={versionId} onChange={(event) => refreshVersion(event.target.value)}>
                  {(dataset?.versions ?? []).map((version) => <option key={version.versionId} value={version.versionId}>{version.versionId}</option>)}
                </select>
              </label>
            </div>
            <div className="mt-4 grid gap-3 md:grid-cols-4">
              <Metric label="Rows" value={(profile?.rowCount ?? dataset?.latestVersion?.rowCount ?? rows.length).toLocaleString()} />
              <Metric label="Columns" value={(profile?.columnCount ?? columns.length).toLocaleString()} />
              <Metric label="Preview rows" value={rows.length.toLocaleString()} />
              <Metric label="Target" value={target || "Not selected"} />
            </div>
            <div className="mt-5 rounded-xl border border-slate-200 bg-slate-50 p-4">
              <div className="flex items-center gap-2">
                <Database size={17} className="text-slate-700" />
                <h3 className="text-sm font-semibold text-slate-950">Add Comparison / Join Dataset</h3>
              </div>
              <div className="mt-3 grid gap-3 lg:grid-cols-4">
                <select className="rounded-lg border border-slate-300 px-3 py-2 text-sm" value={secondaryDatasetId} onChange={(event) => setSecondaryDatasetId(event.target.value)}>
                  <option value="">No secondary dataset</option>
                  {datasets.filter((item) => item.datasetId !== datasetId).map((item) => <option key={item.datasetId} value={item.datasetId}>{item.name}</option>)}
                </select>
                <select className="rounded-lg border border-slate-300 px-3 py-2 text-sm" value={joinKey} onChange={(event) => setJoinKey(event.target.value)} disabled={!secondaryDatasetId}>
                  <option value="">Join key...</option>
                  {columns.filter((column) => secondaryPreview?.columns?.includes(column)).map((column) => <option key={column}>{column}</option>)}
                </select>
                <select className="rounded-lg border border-slate-300 px-3 py-2 text-sm" value={joinType} onChange={(event) => setJoinType(event.target.value)} disabled={!secondaryDatasetId}>
                  {["inner", "left", "right", "outer", "append/union"].map((item) => <option key={item}>{item}</option>)}
                </select>
                <div className="rounded-lg border border-slate-200 bg-white px-3 py-2 text-xs text-slate-600">
                  Secondary rows: {secondaryPreview?.rows?.length?.toLocaleString?.() ?? "-"}
                </div>
              </div>
              <p className="mt-2 text-xs text-slate-500">
                V1 generates governed Python and SQL join templates. Full backend join execution is not enabled yet.
              </p>
            </div>
          </WorkbenchSection>

          <WorkbenchSection id="analyze" title="Analytical Modules" tone="emerald">
            <div className="grid gap-5 xl:grid-cols-2">
              <Card title="Column Explorer" icon={<Search size={18} />}>
                <select className="rounded-lg border border-slate-300 px-3 py-2 text-sm" value={selectedColumn} onChange={(event) => setSelectedColumn(event.target.value)}>
                  {columns.map((column) => <option key={column} value={column}>{column}</option>)}
                </select>
                {selectedSummary.kind === "numeric" ? <NumericColumnView summary={selectedSummary.summary} values={numericValues(rows, selectedColumn)} column={selectedColumn} /> : <CategoricalColumnView rows={rows} column={selectedColumn} />}
                <ExportResultActions resultType="column_explorer" payload={columnExplorerExportPayload()} onExport={downloadResultExport} />
              </Card>
              <Card title="Target Relationship Explorer" icon={<BarChart3 size={18} />}>
                <select className="rounded-lg border border-slate-300 px-3 py-2 text-sm" value={target} onChange={(event) => setTarget(event.target.value)}>
                  <option value="">Select target...</option>
                  {columns.map((column) => <option key={column} value={column}>{column}</option>)}
                </select>
                <TargetPanel target={target} summary={targetSummary} />
                <ExportResultActions resultType="target_relationship" payload={targetRelationshipExportPayload()} onExport={downloadResultExport} />
              </Card>
              <Card title="Group Comparison" icon={<BarChart3 size={18} />}>
                <div className="grid gap-2 md:grid-cols-3">
                  <select className="rounded-lg border px-2 py-2 text-sm" value={groupColumn} onChange={(event) => setGroupColumn(event.target.value)}>{columns.map((column) => <option key={column}>{column}</option>)}</select>
                  <select className="rounded-lg border px-2 py-2 text-sm" value={metricColumn} onChange={(event) => setMetricColumn(event.target.value)}>{numericColumns.map((column) => <option key={column}>{column}</option>)}</select>
                  <select className="rounded-lg border px-2 py-2 text-sm" value={aggregation} onChange={(event) => setAggregation(event.target.value)}>{["count", "mean", "median", "sum", "min", "max", "std", "event rate"].map((item) => <option key={item}>{item}</option>)}</select>
                </div>
                <GroupComparison rows={groupRows} metric={aggregation} />
                <ExportResultActions resultType="group_comparison" payload={groupComparisonExportPayload()} onExport={downloadResultExport} />
              </Card>
              <Card title="Data Quality Review" icon={<FileText size={18} />}>
                <MiniCorrelation pairs={correlations} />
                <QualityList findings={quality.slice(0, 5)} />
                <ExportResultActions resultType="data_quality" payload={dataQualityExportPayload()} onExport={downloadResultExport} />
              </Card>
            </div>
            <div className="mt-5 rounded-xl border border-emerald-200 bg-emerald-50 p-4">
              <div className="text-xs font-semibold uppercase tracking-wide text-emerald-800">Recommended Analyses for This Question</div>
              <div className="mt-3 grid gap-2 md:grid-cols-2">
                {recommendedAnalyses.map((item) => (
                  <div key={item} className="rounded-lg border border-emerald-200 bg-white px-3 py-2 text-sm text-emerald-950">{item}</div>
                ))}
              </div>
            </div>
            <div className="mt-5 rounded-xl border border-slate-200 bg-white p-5 shadow-sm">
              <div className="flex flex-col gap-3 lg:flex-row lg:items-center lg:justify-between">
                <div>
                  <h3 className="text-base font-semibold text-slate-950">Pivot Table Builder</h3>
                  <p className="mt-1 text-sm text-slate-600">Create quick dataset summaries without writing Python or SQL.</p>
                </div>
                <button type="button" onClick={savePivotInsight} className="rounded-lg bg-emerald-700 px-3 py-2 text-sm font-semibold text-white shadow-sm hover:bg-emerald-800">
                  Save Pivot as Insight
                </button>
              </div>
              <div className="mt-4 grid gap-3 lg:grid-cols-6">
                <label className="grid gap-1 text-xs font-semibold uppercase tracking-wide text-slate-500">
                  Rows
                  <select className="rounded-lg border border-slate-300 px-2 py-2 text-sm font-normal normal-case text-slate-900" value={pivotRowField} onChange={(event) => setPivotRowField(event.target.value)}>
                    {columns.map((column) => <option key={column}>{column}</option>)}
                  </select>
                </label>
                <label className="grid gap-1 text-xs font-semibold uppercase tracking-wide text-slate-500">
                  Columns
                  <select className="rounded-lg border border-slate-300 px-2 py-2 text-sm font-normal normal-case text-slate-900" value={pivotColumnField} onChange={(event) => setPivotColumnField(event.target.value)}>
                    <option value="">None</option>
                    {columns.filter((column) => column !== pivotRowField).map((column) => <option key={column}>{column}</option>)}
                  </select>
                </label>
                <label className="grid gap-1 text-xs font-semibold uppercase tracking-wide text-slate-500">
                  Values
                  <select className="rounded-lg border border-slate-300 px-2 py-2 text-sm font-normal normal-case text-slate-900" value={pivotValueField} onChange={(event) => setPivotValueField(event.target.value)}>
                    {numericColumns.map((column) => <option key={column}>{column}</option>)}
                  </select>
                </label>
                <label className="grid gap-1 text-xs font-semibold uppercase tracking-wide text-slate-500">
                  Aggregation
                  <select className="rounded-lg border border-slate-300 px-2 py-2 text-sm font-normal normal-case text-slate-900" value={pivotAggregation} onChange={(event) => setPivotAggregation(event.target.value)}>
                    {["count", "sum", "mean", "median", "min", "max", "std dev", "event rate"].map((item) => <option key={item}>{item}</option>)}
                  </select>
                </label>
                <label className="grid gap-1 text-xs font-semibold uppercase tracking-wide text-slate-500">
                  Top-N
                  <input className="rounded-lg border border-slate-300 px-2 py-2 text-sm font-normal normal-case text-slate-900" type="number" min={3} max={50} value={pivotTopN} onChange={(event) => setPivotTopN(Number(event.target.value) || 12)} />
                </label>
                <div className="grid gap-2">
                  <label className="flex items-center gap-2 rounded-lg border border-slate-200 bg-slate-50 px-3 py-2 text-xs font-semibold text-slate-700">
                    <input type="checkbox" checked={pivotAutoBinRows} onChange={(event) => setPivotAutoBinRows(event.target.checked)} />
                    Auto-bin numeric row fields into quantiles
                  </label>
                  <label className="flex items-center gap-2 rounded-lg border border-slate-200 bg-slate-50 px-3 py-2 text-xs font-semibold text-slate-700">
                    <input type="checkbox" checked={pivotAutoBinColumns} onChange={(event) => setPivotAutoBinColumns(event.target.checked)} />
                    Auto-bin numeric column fields into quantiles
                  </label>
                </div>
              </div>
              <div className="mt-4 grid gap-4 xl:grid-cols-[1fr_300px]">
                <div className="space-y-3">
                  <PivotTable result={pivot} />
                  <ExportResultActions resultType="pivot" payload={pivotExportPayload()} onExport={downloadResultExport} />
                </div>
                <div className="rounded-xl border border-blue-200 bg-blue-50 p-4">
                  <div className="text-xs font-semibold uppercase tracking-wide text-blue-700">Pivot Readout</div>
                  <p className="mt-2 text-sm leading-6 text-blue-950">{pivot.readout}</p>
                  <div className="mt-4">
                    <BarList rows={pivotChartRows(pivot)} title="Pivot Summary Chart" />
                  </div>
                </div>
              </div>
            </div>
          </WorkbenchSection>

          <WorkbenchSection id="code" title="Code Workspace" tone="slate">
            <div className="mb-4 rounded-2xl border border-slate-200 bg-white p-4 shadow-sm">
              <div className="flex flex-col gap-3 lg:flex-row lg:items-center lg:justify-between">
                <div>
                  <h3 className="text-sm font-semibold text-slate-950">Code Runtime Configuration</h3>
                  <p className="mt-1 text-xs text-slate-600">Local execution uses the ATLAS Python engine, SQLite preview SQL, Rscript when installed, and SAS-compatible execution with no SAS license required.</p>
                </div>
                <button type="button" onClick={refreshRuntimeDiagnostics} className="rounded-lg border border-blue-200 bg-white px-3 py-2 text-sm font-semibold text-blue-800">
                  Refresh Runtime Diagnostics
                </button>
              </div>
              <div className="mt-3 grid gap-2 md:grid-cols-4">
                <Metric label="Python" value={pythonDiagnostics?.canStartPython ? "Executable" : "Unknown"} />
                <Metric label="Pandas" value={pythonDiagnostics?.canImportPandas ? "Available" : "Unavailable"} />
                <Metric label="SQL Preview" value="SQLite SELECT" />
                <Metric label="Rscript" value={pythonDiagnostics?.rExecutionAvailable ? "Executable" : "Template only"} />
                <Metric label="R Path" value={pythonDiagnostics?.rscriptPath || "Not found"} />
                <Metric label="SAS-Compatible Engine" value={sasDiagnostics?.sasCompatibleAvailable ? "Available" : "Unavailable"} />
                <Metric label="SAS-Compatible PROCs" value={(sasDiagnostics?.sasCompatibleSupportedProcs ?? ["CONTENTS", "MEANS", "FREQ", "CORR", "PRINT", "SQL", "RANK"]).join(", ")} />
                <Metric label="SASPy" value={sasDiagnostics?.saspyInstalled ? "Installed" : "Not installed"} />
                <Metric label="Licensed SAS Bridge" value={sasDiagnostics?.sasExecutionAvailable ? "Executable" : sasDiagnostics?.sasExecutionMode === "saspy_config" ? "Configured" : "Optional"} />
              </div>
              <div className="mt-4 rounded-xl border border-emerald-200 bg-emerald-50 p-4">
                <div className="flex flex-col gap-2 lg:flex-row lg:items-start lg:justify-between">
                  <div>
                    <h4 className="text-sm font-semibold text-slate-950">SAS Mode: ATLAS SAS-Compatible</h4>
                    <p className="mt-1 max-w-3xl text-xs leading-5 text-emerald-950">
                      Executable by default. ATLAS runs a supported subset of familiar SAS-style PROC and DATA step syntax through the local Python execution engine. No SAS license, SASPy, Java, SAS Studio, or SAS Viya connection is required.
                    </p>
                  </div>
                  <span className="rounded-full bg-emerald-100 px-2 py-1 text-xs font-semibold uppercase text-emerald-800">Executable</span>
                </div>
              </div>
              <details className="mt-4 rounded-xl border border-blue-200 bg-blue-50 p-4">
                <summary className="cursor-pointer text-sm font-semibold text-slate-950">Advanced: Licensed SAS Bridge</summary>
                <div className="flex flex-col gap-3 lg:flex-row lg:items-start lg:justify-between">
                  <div>
                    <h4 className="mt-4 text-sm font-semibold text-slate-950">Optional SASPy Runtime Setup</h4>
                    <p className="mt-1 max-w-3xl text-xs leading-5 text-slate-600">
                      This bridge is only for users who already have access to a licensed SAS runtime. It is not needed for ATLAS SAS-Compatible execution.
                    </p>
                  </div>
                  <span className={`rounded-full px-2 py-1 text-xs font-semibold uppercase ${sasDiagnostics?.sasExecutionAvailable ? "bg-emerald-100 text-emerald-800" : "bg-blue-100 text-blue-800"}`}>
                    {sasDiagnostics?.connectionMethod ?? "Template only"}
                  </span>
                </div>
                <div className="mt-3 grid gap-2 md:grid-cols-4">
                  <Metric label="SASPy Version" value={sasDiagnostics?.saspyVersion || "-"} />
                  <Metric label="SASPy Module" value={sasDiagnostics?.saspyModulePath || "-"} />
                  <Metric label="Active cfgname" value={sasDiagnostics?.activeCfgName || "-"} />
                  <Metric label="Last Test" value={sasDiagnostics?.lastConnectionTest || "Not tested"} />
                </div>
                <div className="mt-4 grid gap-3 lg:grid-cols-[220px_1fr_1fr]">
                  <label className="grid gap-1 text-xs font-semibold uppercase tracking-wide text-slate-600">
                    SAS execution mode
                    <select className="rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm font-normal normal-case text-slate-900" value={sasMode} onChange={(event) => setSasMode(event.target.value as SasExecutionMode)}>
                      <option value="template_only">Template only</option>
                      <option value="saspy_config">SASPy configured session</option>
                      <option value="external_export">External SAS export only</option>
                    </select>
                    <span className="text-[11px] font-normal normal-case leading-4 text-slate-500">Template mode validates/export code. SASPy mode runs only after a successful connection test.</span>
                  </label>
                  <label className="grid gap-1 text-xs font-semibold uppercase tracking-wide text-slate-600">
                    SASPy cfgname
                    <input className="rounded-lg border border-slate-300 px-3 py-2 text-sm font-normal normal-case text-slate-900" value={sasCfgname} onChange={(event) => setSasCfgname(event.target.value)} placeholder="winlocal, iomlinux, viya..." disabled={sasMode !== "saspy_config"} />
                    <span className="text-[11px] font-normal normal-case leading-4 text-slate-500">Name of a SASPy configuration. Do not enter passwords or tokens.</span>
                  </label>
                  <label className="grid gap-1 text-xs font-semibold uppercase tracking-wide text-slate-600">
                    SASPy cfgfile path
                    <input className="rounded-lg border border-slate-300 px-3 py-2 text-sm font-normal normal-case text-slate-900" value={sasCfgfile} onChange={(event) => setSasCfgfile(event.target.value)} placeholder="C:/Users/james/path/to/sascfg_personal.py" disabled={sasMode !== "saspy_config"} />
                    <span className="text-[11px] font-normal normal-case leading-4 text-slate-500">Optional path to a SASPy config file. The file must already exist.</span>
                  </label>
                </div>
                <div className="mt-3 flex flex-wrap gap-2">
                  <button type="button" onClick={() => saveSasSettings()} disabled={savingSasSettings} className="rounded-lg bg-slate-950 px-3 py-2 text-sm font-semibold text-white disabled:bg-slate-400">
                    {savingSasSettings ? "Saving..." : "Save SAS Runtime Settings"}
                  </button>
                  <button type="button" onClick={runSasConnectionTest} disabled={testingSasConnection} className="rounded-lg border border-blue-300 bg-white px-3 py-2 text-sm font-semibold text-blue-800 disabled:text-slate-400">
                    {testingSasConnection ? "Testing..." : "Test SAS Connection"}
                  </button>
                  <button type="button" onClick={resetSasTemplateOnly} className="rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm font-semibold text-slate-700">
                    Reset to Template Only
                  </button>
                </div>
                {sasDiagnostics?.lastError ? <div className="mt-3 rounded-lg border border-amber-200 bg-amber-50 px-3 py-2 text-xs leading-5 text-amber-900">Last SAS error: {sasDiagnostics.lastError}</div> : null}
                <div className="mt-4 grid gap-3 lg:grid-cols-2">
                  <div className="rounded-lg border border-slate-200 bg-white p-3">
                    <div className="text-xs font-semibold uppercase tracking-wide text-slate-600">Detected SAS Config Files</div>
                    <ul className="mt-2 space-y-1 text-xs leading-5 text-slate-700">
                      {(sasDiagnostics?.detectedConfigFiles?.length ? sasDiagnostics.detectedConfigFiles : ["No SASPy config files detected yet."]).map((item) => <li key={item} className="break-all">{item}</li>)}
                    </ul>
                  </div>
                  <div className="rounded-lg border border-slate-200 bg-white p-3">
                    <div className="text-xs font-semibold uppercase tracking-wide text-slate-600">Setup Guidance</div>
                    <ul className="mt-2 list-disc space-y-1 pl-5 text-xs leading-5 text-slate-700">
                      {(sasDiagnostics?.setupGuidance?.length ? sasDiagnostics.setupGuidance : ["Choose Template only for external SAS execution, or configure SASPy with a licensed SAS runtime to run SAS inside ATLAS."]).slice(0, 5).map((item) => <li key={item}>{item}</li>)}
                    </ul>
                  </div>
                </div>
                <div className="mt-3 rounded-lg border border-slate-200 bg-white p-3 text-xs leading-5 text-slate-700">
                  <div className="font-semibold text-slate-950">Which SAS setup do you have?</div>
                  <div className="mt-2 grid gap-2 md:grid-cols-2">
                    <div><span className="font-semibold">Local SAS:</span> ATLAS needs a working SASPy cfgname/cfgfile that can start a local licensed SAS session.</div>
                    <div><span className="font-semibold">Remote SAS server:</span> ATLAS needs a SASPy config pointing to the remote server. Do not store credentials in ATLAS.</div>
                    <div><span className="font-semibold">SAS Studio / Viya:</span> ATLAS needs a SASPy config that can connect to the SAS Viya environment.</div>
                    <div><span className="font-semibold">Export only:</span> ATLAS generates SAS programs for external execution but does not run them inside ATLAS.</div>
                  </div>
                </div>
              </details>
            </div>
            <CodeWorkspacePanel
              activeLanguage={activeCodeLanguage}
              onActiveLanguageChange={setActiveCodeLanguage}
              cleanStderr={cleanPythonStderr}
              languages={[
                {
                  language: "python",
                  label: "Python",
                  supportBadge: "executable",
                  generatedCode: generatedPython,
                  userCode: userPython,
                  setUserCode: setUserPython,
                  runLabel: "Run User Python",
                  canRun: true,
                  running: runningPython,
                  result: pythonOutput,
                  diagnostics: pythonDiagnostics,
                  onRun: runPython,
                  onCopy: () => copyText(userPython || generatedPython),
                  onSave: () => saveCodeInsight("python", userPython || generatedPython),
                  note: "Executable locally through /api/python/run. ATLAS injects preview_rows and creates df from the selected dataset preview when pandas is available.",
                },
                {
                  language: "sql",
                  label: "SQL",
                  supportBadge: "preview SQL",
                  generatedCode: generatedSql,
                  userCode: userSql,
                  setUserCode: setUserSql,
                  runLabel: "Run SQL on Preview",
                  canRun: true,
                  running: runningSql,
                  result: sqlResult,
                  onRun: runSqlOnPreview,
                  onCopy: () => copyText(userSql || generatedSql),
                  onSave: () => saveCodeInsight("sql", userSql || generatedSql),
                  note: "Executable over preview/sample rows using safe SELECT-only in-memory SQLite. Full warehouse-scale execution is deferred.",
                },
                {
                  language: "r",
                  label: "R",
                  supportBadge: pythonDiagnostics?.rExecutionAvailable ? "executable" : "template only",
                  generatedCode: generatedR,
                  userCode: userR,
                  setUserCode: setUserR,
                  runLabel: pythonDiagnostics?.rExecutionAvailable ? "Run R" : "Validate Template",
                  canRun: true,
                  running: runningR,
                  result: rResult,
                  onRun: runRCode,
                  onCopy: () => copyText(userR || generatedR),
                  onSave: () => saveCodeInsight("r", userR || generatedR),
                  note: pythonDiagnostics?.rExecutionAvailable ? "Rscript is detected. ATLAS executes R locally against a temporary preview CSV." : "R execution is not configured on this machine. Install R and ensure Rscript is on PATH to enable local R execution.",
                },
                {
                  language: "sas",
                  label: "SAS",
                  supportBadge: "SAS-compatible",
                  generatedCode: generatedSas,
                  userCode: userSas,
                  setUserCode: setUserSas,
                  runLabel: "Run SAS-Compatible Code",
                  canRun: true,
                  running: runningSas,
                  result: sasResult,
                  onRun: runSasCompatibleCode,
                  onCopy: () => copyText(userSas || generatedSas),
                  onSave: () => saveCodeInsight("sas", userSas || generatedSas),
                  note: "ATLAS runs a supported subset of SAS-style code using the local Python execution engine. No SAS license is required. Unsupported SAS statements are listed with guidance instead of crashing the app.",
                },
              ]}
            />
            <div className="mt-4 rounded-xl border border-slate-200 bg-white p-4">
              <div className="flex flex-col gap-3 md:flex-row md:items-center md:justify-between">
                <div>
                  <div className="text-sm font-semibold text-slate-950">Export Code Workspace Result</div>
                  <p className="mt-1 text-xs text-slate-500">Exports the current package, including generated code, user-edited code, and the latest execution output.</p>
                </div>
                {activeExecutionResult ? (
                  <ExportResultActions resultType={`${activeCodeLanguage === "sas" ? "sas_compatible" : activeCodeLanguage}_result`} payload={codeResultExportPayload()} onExport={downloadResultExport} />
                ) : (
                  <span className="text-xs text-slate-500">Run code to enable result-level Excel export.</span>
                )}
              </div>
            </div>
          </WorkbenchSection>
        </main>

        <aside id="insights" className="space-y-5">
          <section className="rounded-2xl border border-blue-200 bg-blue-50 p-5 shadow-sm">
            <div className="flex items-center gap-2">
              <Brain size={18} className="text-blue-700" />
              <h2 className="text-base font-semibold text-slate-950">Insight Assistant</h2>
            </div>
            <p className="mt-3 text-sm leading-6 text-slate-700">{assistantText}</p>
            <div className="mt-4 grid gap-2">
              <div className="grid gap-2">
                <button className="rounded-lg bg-slate-950 px-3 py-2 text-sm font-semibold text-white" onClick={keyTakeaways}>Generate Key Takeaways</button>
                <button className="rounded-lg border border-blue-200 bg-white px-3 py-2 text-sm font-semibold text-blue-800" onClick={generatePlan}>Generate Analysis Plan</button>
              </div>
              <div className="rounded-xl border border-blue-100 bg-white p-3">
                <div className="text-xs font-semibold uppercase tracking-wide text-blue-700">Use Generated Code</div>
                <div className="mt-2 grid grid-cols-2 gap-2">
                  {(["python", "sql", "r", "sas"] as CodeLanguage[]).map((language) => (
                    <button key={language} className="rounded-lg border border-blue-200 bg-blue-50 px-2 py-2 text-xs font-semibold text-blue-900 hover:border-blue-400" onClick={() => useGeneratedCode(language)}>
                      {languageCode[language].label}
                    </button>
                  ))}
                </div>
              </div>
              <button className="inline-flex items-center justify-center gap-2 rounded-lg bg-emerald-700 px-3 py-2 text-sm font-semibold text-white" onClick={() => saveInsight("workbench_summary")}><Save size={15} /> Save Insight</button>
              <button className="rounded-lg border border-emerald-200 bg-white px-3 py-2 text-sm font-semibold text-emerald-800" onClick={() => saveCodeInsight(activeCodeLanguage, activeLanguageCode.user || activeLanguageCode.generated)}>Save {activeLanguageCode.label} Code Snippet</button>
              <button className="rounded-lg border border-emerald-200 bg-white px-3 py-2 text-sm font-semibold text-emerald-800" onClick={() => saveInsight("analysis_plan")}>Save Analysis Plan</button>
              <div className="rounded-xl border border-slate-200 bg-white p-3">
                <div className="text-xs font-semibold uppercase tracking-wide text-slate-600">Export Analysis</div>
                <ExportButtonRow label="Export Analysis" onExport={(format) => downloadExport(format)} compact fullLabels />
                <button className="mt-2 w-full rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm font-semibold text-slate-700" onClick={() => exportInsight(currentExportPayload())}>Export JSON</button>
              </div>
            </div>
          </section>
          <Card title="Dataset Context" icon={<Database size={18} />}>
            <SummaryGrid items={[["Dataset", dataset?.name ?? "-"], ["Version", versionId || "-"], ["Rows", profile?.rowCount?.toLocaleString() ?? "-"], ["Secondary", secondaryDataset?.name ?? "None"], ["Linked project", projectId || "-"]]} />
          </Card>
          <Card title="Saved Findings" icon={<FileText size={18} />}>
            <div className="mb-3 flex flex-wrap gap-2">
              {["all", "insights", "code", "pivot", "questions", "plans"].map((filter) => (
                <button
                  key={filter}
                  type="button"
                  onClick={() => setInsightFilter(filter)}
                  className={`rounded-full border px-2.5 py-1 text-xs font-semibold capitalize ${insightFilter === filter ? "border-blue-300 bg-blue-50 text-blue-800" : "border-slate-200 bg-white text-slate-600"}`}
                >
                  {filter}
                </button>
              ))}
            </div>
            {filteredInsights.length ? filteredInsights.map((insight) => (
              <SavedFindingItem key={insight.insightId} insight={insight} datasetName={dataset?.name ?? datasetId} onExport={downloadExport} />
            )) : <div className="rounded-lg border border-slate-200 bg-slate-50 px-3 py-2 text-sm text-slate-500">No saved findings match this filter.</div>}
          </Card>
        </aside>
      </section>
    </div>
  );
}

function WorkbenchSection({ id, title, tone, children }: { id: string; title: string; tone: "blue" | "emerald" | "slate"; children: React.ReactNode }) {
  const styles = tone === "blue" ? "border-blue-200 bg-blue-50/40" : tone === "emerald" ? "border-emerald-200 bg-emerald-50/30" : "border-slate-200 bg-white";
  return (
    <section id={id} className={`rounded-2xl border p-5 shadow-sm ${styles}`}>
      <h2 className="text-lg font-semibold text-slate-950">{title}</h2>
      <div className="mt-4">{children}</div>
    </section>
  );
}

function SavedFindingItem({ insight, datasetName, onExport }: { insight: AtlasAnalyticsInsight; datasetName: string; onExport: (format: AnalyticsExportFormat, insight?: AtlasAnalyticsInsight) => void }) {
  const metrics = insight.evidence?.metrics ?? {};
  const language = normalizeInsightLanguage(String(metrics.language ?? ""));
  const insightType = insight.analysisType.replace(/_/g, " ");
  const badge = language || typeBadge(insight.analysisType);
  return (
    <div className="mb-2 rounded-lg border border-slate-200 bg-slate-50 px-3 py-2 text-sm">
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div className="min-w-0">
          <div className="truncate font-semibold text-slate-950">{insight.title}</div>
          <div className="mt-1 text-xs leading-5 text-slate-500">
            {insightType} - {new Date(insight.createdAt).toLocaleString()} - {String(metrics.datasetName ?? datasetName)}
          </div>
        </div>
        <span className="shrink-0 rounded-full border border-blue-200 bg-blue-50 px-2 py-1 text-[11px] font-semibold text-blue-800">{badge}</span>
      </div>
      <SavedFindingExportMenu onExport={(format) => onExport(format, insight)} />
    </div>
  );
}

function SavedFindingExportMenu({ onExport }: { onExport: (format: AnalyticsExportFormat) => void }) {
  return (
    <details className="mt-2">
      <summary className="inline-flex cursor-pointer rounded-lg border border-slate-200 bg-white px-2 py-1.5 text-xs font-semibold text-slate-700 hover:border-blue-300 hover:text-blue-800">
        Export
      </summary>
      <div className="mt-2 flex flex-wrap gap-2 rounded-lg border border-slate-200 bg-white p-2">
        <button type="button" className="rounded-md px-2 py-1 text-xs font-semibold text-slate-700 hover:bg-slate-50" onClick={() => onExport("excel")}>Excel</button>
        <button type="button" className="rounded-md px-2 py-1 text-xs font-semibold text-slate-700 hover:bg-slate-50" onClick={() => onExport("word")}>Word</button>
        <button type="button" className="rounded-md px-2 py-1 text-xs font-semibold text-slate-700 hover:bg-slate-50" onClick={() => onExport("powerpoint")}>PowerPoint</button>
      </div>
    </details>
  );
}

function ExportButtonRow({ label, onExport, compact = false, fullLabels = false }: { label: string; onExport: (format: AnalyticsExportFormat) => void; compact?: boolean; fullLabels?: boolean }) {
  const buttonClass = compact
    ? "rounded-lg border border-slate-200 bg-white px-2 py-1.5 text-xs font-semibold text-slate-700 hover:border-blue-300 hover:text-blue-800"
    : "rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm font-semibold text-slate-700 hover:border-blue-300 hover:text-blue-800";
  return (
    <div className={`flex flex-wrap items-center gap-2 ${compact ? "mt-2" : ""}`} aria-label={label}>
      <button type="button" className={buttonClass} onClick={() => onExport("excel")}>{fullLabels ? "Export to Excel" : "Excel"}</button>
      <button type="button" className={buttonClass} onClick={() => onExport("word")}>{fullLabels ? "Export to Word" : "Word"}</button>
      <button type="button" className={buttonClass} onClick={() => onExport("powerpoint")}>{fullLabels ? "Export to PowerPoint" : "PowerPoint"}</button>
    </div>
  );
}

function normalizeInsightLanguage(language: string) {
  if (language === "python") return "Python";
  if (language === "sql") return "SQL";
  if (language === "r") return "R";
  if (language === "sas") return "SAS-compatible";
  return "";
}

function typeBadge(analysisType: string) {
  if (analysisType.includes("pivot")) return "Pivot";
  if (analysisType.includes("question")) return "Question";
  if (analysisType.includes("plan")) return "Plan";
  return "Insight";
}

function filterInsights(insights: AtlasAnalyticsInsight[], filter: string) {
  if (filter === "all") return insights;
  return insights.filter((insight) => {
    const type = insight.analysisType;
    if (filter === "code") return type.includes("code_snippet");
    if (filter === "pivot") return type.includes("pivot");
    if (filter === "questions") return type.includes("question");
    if (filter === "plans") return type.includes("plan");
    if (filter === "insights") return !type.includes("code_snippet") && !type.includes("pivot") && !type.includes("question") && !type.includes("plan");
    return true;
  });
}

function buildExportPayload(input: {
  businessQuestion: string;
  cleanedQuestion: string;
  analysisPlan: string[];
  generatedPython: string;
  generatedSql: string;
  generatedR: string;
  generatedSas: string;
  userPython: string;
  userSql: string;
  userR: string;
  userSas: string;
  activeLanguage: CodeLanguage;
  activeCode: string;
  dataset: DatasetSummary | null;
  datasetId: string;
  versionId: string;
  projectId: string;
  target: string;
  previewRowCount: number;
  pivot: PivotResult;
  sqlResult: AnalyticsSqlRunResult | null;
  sasResult: CodeRunResult | null;
  pythonResult: PythonExecutionResult | null;
  rResult: CodeRunResult | null;
  savedInsight?: AtlasAnalyticsInsight;
  metadata?: Record<string, unknown>;
}) {
  const datasetName = input.dataset?.name ?? input.datasetId;
  return {
    exportTitle: `ATLAS Analytics Workbench Report - ${datasetName}`,
    exportedAt: new Date().toISOString(),
    createdAt: new Date().toISOString(),
    createdBy: "ATLAS local user",
    businessQuestion: input.businessQuestion,
    cleanedQuestion: input.cleanedQuestion,
    analysisPlan: input.analysisPlan,
    datasetName,
    datasetId: input.datasetId,
    versionId: input.versionId,
    targetVariable: input.target,
    previewRowCount: input.previewRowCount,
    dataset: {
      datasetId: input.datasetId,
      name: datasetName,
      versionId: input.versionId,
    },
    linkedProjectId: input.projectId,
    generatedPython: input.generatedPython,
    generatedSql: input.generatedSql,
    generatedR: input.generatedR,
    generatedSas: input.generatedSas,
    userEditedPython: input.userPython,
    userEditedSql: input.userSql,
    userEditedR: input.userR,
    userEditedSas: input.userSas,
    activeLanguage: input.activeLanguage,
    activeCode: input.activeCode,
    pivotConfig: input.pivot.config,
    pivotRows: input.pivot.rows.slice(0, 250),
    pivotPreview: input.pivot.rows.slice(0, 20),
    pivotReadout: input.pivot.readout,
    sqlResult: input.sqlResult ?? {},
    sasResult: input.sasResult ?? {},
    pythonResult: input.pythonResult ?? {},
    rResult: input.rResult ?? {},
    savedInsight: input.savedInsight ?? {},
    metadata: input.metadata ?? {},
    limitations: "Analytics Workbench results are based on the current dataset preview and selected saved findings. Validate against governed full-data execution before using in production decisions.",
  };
}

function isNumericColumn(rows: Record<string, unknown>[], column: string) {
  const values = rows.map((row) => row[column]).filter((value) => value !== null && value !== undefined && value !== "");
  if (!values.length) return false;
  return values.slice(0, 50).every((value) => Number.isFinite(Number(value)));
}

function numericValues(rows: Record<string, unknown>[], column: string) {
  return rows.map((row) => Number(row[column])).filter((value) => Number.isFinite(value));
}

function numericSummaryRows(summary: NumericSummary): Array<[string, string | number]> {
  return [
    ["Count", summary.count],
    ["Mean", summary.mean],
    ["Median", summary.median],
    ["Std dev", summary.std],
    ["Min", summary.min],
    ["Max", summary.max],
    ["P5", summary.p5],
    ["P25", summary.p25],
    ["P50", summary.p50],
    ["P75", summary.p75],
    ["P95", summary.p95],
    ["Missing %", summary.missingPct],
    ["Distinct count", summary.distinct],
  ];
}

function histogramBins(values: number[]) {
  const min = Math.min(...values, 0);
  const max = Math.max(...values, 1);
  const bins = Array.from({ length: 12 }, (_, index) => ({ bin: index + 1, rangeStart: min + ((max - min) / 12) * index, rangeEnd: min + ((max - min) / 12) * (index + 1), count: 0 }));
  values.forEach((value) => {
    const idx = Math.min(11, Math.max(0, Math.floor(((value - min) / Math.max(0.000001, max - min)) * 12)));
    bins[idx].count += 1;
  });
  return bins;
}

function resultExportTitle(resultType: string) {
  const labels: Record<string, string> = {
    column_explorer: "Column Explorer",
    target_relationship: "Target Relationship",
    group_comparison: "Group Comparison",
    data_quality: "Data Quality",
    pivot: "Pivot",
    sql_result: "SQL Result",
    sas_compatible_result: "SAS Compatible Result",
    r_result: "R Result",
    python_result: "Python Result",
  };
  return labels[resultType] ?? "Analytics Result";
}

function quantile(values: number[], q: number) {
  if (!values.length) return 0;
  const sorted = [...values].sort((a, b) => a - b);
  const pos = (sorted.length - 1) * q;
  const base = Math.floor(pos);
  const rest = pos - base;
  return sorted[base] + ((sorted[base + 1] ?? sorted[base]) - sorted[base]) * rest;
}

function summarizeNumeric(rows: Record<string, unknown>[], column: string): NumericSummary {
  const values = numericValues(rows, column);
  const mean = values.reduce((sum, value) => sum + value, 0) / Math.max(1, values.length);
  const std = Math.sqrt(values.reduce((sum, value) => sum + (value - mean) ** 2, 0) / Math.max(1, values.length - 1));
  const missing = rows.length - values.length;
  return {
    count: values.length,
    mean,
    median: quantile(values, 0.5),
    std,
    min: values.length ? Math.min(...values) : 0,
    max: values.length ? Math.max(...values) : 0,
    p5: quantile(values, 0.05),
    p25: quantile(values, 0.25),
    p50: quantile(values, 0.5),
    p75: quantile(values, 0.75),
    p95: quantile(values, 0.95),
    missingPct: rows.length ? missing / rows.length : 0,
    distinct: new Set(values).size,
  };
}

function summarizeColumn(rows: Record<string, unknown>[], column: string): { kind: "numeric"; summary: NumericSummary } | { kind: "categorical" } {
  return isNumericColumn(rows, column) ? { kind: "numeric", summary: summarizeNumeric(rows, column) } : { kind: "categorical" };
}

function counts(rows: Record<string, unknown>[], column: string) {
  const map = new Map<string, number>();
  rows.forEach((row) => {
    const key = String(row[column] ?? "Missing");
    map.set(key, (map.get(key) ?? 0) + 1);
  });
  return [...map.entries()].sort((a, b) => b[1] - a[1]).slice(0, 12);
}

function groupComparison(rows: Record<string, unknown>[], groupColumn: string, metricColumn: string, aggregation: string, target: string) {
  const map = new Map<string, number[]>();
  rows.forEach((row) => {
    const key = String(row[groupColumn] ?? "Missing");
    const metric = aggregation === "event rate" ? Number(row[target]) : Number(row[metricColumn]);
    if (!map.has(key)) map.set(key, []);
    if (Number.isFinite(metric)) map.get(key)?.push(metric);
  });
  return [...map.entries()].map(([group, values]) => {
    const value =
      aggregation === "count" ? values.length :
      aggregation === "median" ? quantile(values, 0.5) :
      aggregation === "sum" ? values.reduce((a, b) => a + b, 0) :
      aggregation === "min" ? Math.min(...values, 0) :
      aggregation === "max" ? Math.max(...values, 0) :
      aggregation === "std" ? summarizeArray(values).std :
      values.reduce((a, b) => a + b, 0) / Math.max(1, values.length);
    return { group, value, n: values.length };
  }).sort((a, b) => b.value - a.value).slice(0, 10);
}

function summarizeArray(values: number[]) {
  const mean = values.reduce((sum, value) => sum + value, 0) / Math.max(1, values.length);
  return { mean, std: Math.sqrt(values.reduce((sum, value) => sum + (value - mean) ** 2, 0) / Math.max(1, values.length - 1)) };
}

function corr(a: number[], b: number[]) {
  const n = Math.min(a.length, b.length);
  if (n < 3) return 0;
  const aa = a.slice(0, n);
  const bb = b.slice(0, n);
  const ma = aa.reduce((s, v) => s + v, 0) / n;
  const mb = bb.reduce((s, v) => s + v, 0) / n;
  const numerator = aa.reduce((s, v, i) => s + (v - ma) * (bb[i] - mb), 0);
  const denominator = Math.sqrt(aa.reduce((s, v) => s + (v - ma) ** 2, 0) * bb.reduce((s, v) => s + (v - mb) ** 2, 0));
  return denominator ? numerator / denominator : 0;
}

function topCorrelations(rows: Record<string, unknown>[], numericColumns: string[]) {
  const pairs: Array<{ a: string; b: string; corr: number }> = [];
  for (let i = 0; i < numericColumns.length; i++) {
    for (let j = i + 1; j < numericColumns.length; j++) {
      pairs.push({ a: numericColumns[i], b: numericColumns[j], corr: corr(numericValues(rows, numericColumns[i]), numericValues(rows, numericColumns[j])) });
    }
  }
  return pairs.sort((a, b) => Math.abs(b.corr) - Math.abs(a.corr)).slice(0, 10);
}

function buildTargetSummary(rows: Record<string, unknown>[], target: string, numericColumns: string[], categoricalColumns: string[]) {
  if (!target) return { mode: "none", text: "Select a target to see relationship diagnostics.", rankings: [] as Array<{ feature: string; value: number }> };
  if (isNumericColumn(rows, target)) {
    const targetValues = numericValues(rows, target);
    return {
      mode: "regression",
      text: `${target} appears numeric. ATLAS ranks numeric features by preview correlation with the target.`,
      rankings: numericColumns.filter((column) => column !== target).map((feature) => ({ feature, value: corr(numericValues(rows, feature), targetValues) })).sort((a, b) => Math.abs(b.value) - Math.abs(a.value)).slice(0, 8),
    };
  }
  return {
    mode: "classification",
    text: `${target} appears categorical. ATLAS recommends reviewing event rates by feature bands/categories.`,
    rankings: categoricalColumns.filter((column) => column !== target).slice(0, 8).map((feature) => ({ feature, value: counts(rows, feature).length })),
  };
}

function qualityReview(profile: DatasetProfile | null, rows: Record<string, unknown>[], columns: string[], numericColumns: string[]) {
  const findings: Array<{ type: string; label: string; detail: string; status: "pass" | "warning" | "fail" }> = [];
  profile?.schema?.forEach((column) => {
    if ((column.missingPctSample ?? 0) > 0) findings.push({ type: "missing", label: `${column.name} has missing values`, detail: `${((column.missingPctSample ?? 0) * 100).toFixed(2)}% missing in profile sample.`, status: (column.missingPctSample ?? 0) > 0.2 ? "fail" : "warning" });
    if ((column.distinctSample ?? 0) > 100 && !numericColumns.includes(column.name)) findings.push({ type: "cardinality", label: `${column.name} is high-cardinality`, detail: `${column.distinctSample} distinct values in profile sample.`, status: "warning" });
  });
  columns.forEach((column) => {
    const distinct = new Set(rows.map((row) => row[column])).size;
    if (distinct <= 1) findings.push({ type: "constant", label: `${column} is constant or near-constant`, detail: "Constant fields usually do not help analysis or modeling.", status: "warning" });
    if (/id$|_id|uuid|account|customer/i.test(column)) findings.push({ type: "id", label: `${column} may be an ID/leakage field`, detail: "Review before using as an explanatory variable.", status: "warning" });
  });
  return findings.length ? findings : [{ type: "quality", label: "No major preview/profile issues detected", detail: "Review full data before production conclusions.", status: "pass" as const }];
}

function buildAnalysisPlan(input: { question: string; datasetName: string; target: string; numericColumns: string[]; categoricalColumns: string[]; hasSecondary: boolean }) {
  const target = input.target || "the selected target";
  const plan = [
    `Confirm the distribution and missingness profile for ${target}.`,
    input.numericColumns.length ? `Rank numeric predictors by association with ${target}.` : "Identify numeric fields that can support relationship analysis.",
    input.categoricalColumns.length ? `Compare ${target} across key categorical segments.` : "Create useful bins or groups for comparison.",
    "Review outliers, suspicious ranges, and high-cardinality fields before interpreting results.",
    "Check collinearity or duplicated signal among candidate explanatory fields.",
    "Generate follow-up Python and SQL templates for reproducible analysis.",
  ];
  if (input.hasSecondary) plan.splice(3, 0, "Validate join coverage and compare primary versus secondary dataset records.");
  if (/time|date|trend|season/i.test(input.question)) plan.splice(1, 0, "Create a time trend and rolling average view if a date field is available.");
  if (/quality|missing|duplicate|null/i.test(input.question)) plan.splice(1, 0, "Prioritize missingness, duplicate records, constants, and suspicious range checks.");
  return plan;
}

function recommendAnalyses(question: string, target: string, targetMode: string, columns: string[]) {
  const lower = question.toLowerCase();
  const items = new Set<string>();
  if (targetMode === "regression") {
    ["Target distribution", "Feature correlation ranking", "Binned target means", "Scatterplot or binned scatter", "Outlier review", "Collinearity review"].forEach((item) => items.add(item));
  } else if (targetMode === "classification") {
    ["Event rate", "Event rate by segment", "IV / separation score", "Decile or lift review", "Confusion risk if model output exists"].forEach((item) => items.add(item));
  }
  if (/time|date|trend|season/.test(lower) || columns.some((column) => /date|time/i.test(column))) ["Trend by date", "Rolling average", "Seasonality review", "Before/after comparison"].forEach((item) => items.add(item));
  if (/quality|missing|duplicate|null|range/.test(lower)) ["Missingness", "Duplicate records", "High cardinality", "Constant columns", "Suspicious ranges"].forEach((item) => items.add(item));
  if (!items.size) ["Dataset profile", "Column distribution review", "Group comparison", "Correlation review", "Data quality scan"].forEach((item) => items.add(item));
  return [...items].slice(0, 10);
}

function deterministicQuestionCleanup(question: string, target: string) {
  const trimmed = question.trim().replace(/\s+/g, " ");
  const withoutPunctuation = trimmed.replace(/[?.!]+$/, "");
  const first = withoutPunctuation.charAt(0).toUpperCase() + withoutPunctuation.slice(1);
  if (/which|what|how|why|does|do|is|are|can|should/i.test(first)) return `${first}?`;
  return `Which factors in the selected dataset are most strongly associated with ${target}, and what evidence supports that relationship?`;
}

function buildPivot(rows: Record<string, unknown>[], config: PivotConfig): PivotResult {
  const rowField = config.rowField;
  const valueField = config.valueField;
  if (!rows.length || !rowField || (!valueField && config.aggregation !== "count")) {
    return {
      config,
      columns: ["Segment", config.aggregation],
      rows: [],
      readout: "Select a row field and value field to generate a pivot table from the dataset preview.",
    };
  }

  const rowIsNumeric = isNumericColumn(rows, rowField);
  const columnIsNumeric = !!config.columnField && isNumericColumn(rows, config.columnField);
  const rowLabel = config.autoBinRows && rowIsNumeric ? `${rowField} band` : rowField;
  const columnLabel = config.columnField && config.autoBinColumns && columnIsNumeric ? `${config.columnField} band` : config.columnField;
  const columnValues = config.columnField
    ? [...new Set(rows.map((row) => pivotGroupLabel(rows, row, config.columnField, config.autoBinColumns)))].slice(0, Math.max(2, Math.min(12, config.topN)))
    : [];
  const buckets = new Map<string, Record<string, number[]>>();
  rows.forEach((row) => {
    const bucket = pivotGroupLabel(rows, row, rowField, config.autoBinRows);
    const columnBucket = config.columnField ? pivotGroupLabel(rows, row, config.columnField, config.autoBinColumns) : config.aggregation;
    const metric = config.aggregation === "event rate" ? Number(row[config.binaryTarget]) : Number(row[valueField]);
    if (!buckets.has(bucket)) buckets.set(bucket, {});
    const record = buckets.get(bucket);
    if (!record) return;
    if (!record[columnBucket]) record[columnBucket] = [];
    if (config.aggregation === "count") record[columnBucket].push(1);
    else if (Number.isFinite(metric)) record[columnBucket].push(metric);
  });

  const outputColumns = config.columnField ? [rowLabel, ...columnValues] : [rowLabel, config.aggregation];
  const pivotRows = [...buckets.entries()].map(([bucket, valuesByColumn]) => {
    const result: Record<string, string | number> = { [rowLabel]: bucket };
    if (config.columnField) {
      columnValues.forEach((column) => {
        result[column] = aggregateValues(valuesByColumn[column] ?? [], config.aggregation);
      });
    } else {
      result[config.aggregation] = aggregateValues(valuesByColumn[config.aggregation] ?? [], config.aggregation);
    }
    return result;
  });

  const sortColumn = outputColumns[1];
  const sortedRows = pivotRows
    .sort((a, b) => Number(b[sortColumn] ?? 0) - Number(a[sortColumn] ?? 0))
    .slice(0, Math.max(3, Math.min(50, config.topN)));
  const top = sortedRows[0];
  const topLabel = top ? String(top[rowLabel] ?? "-") : "-";
  const topValue = top ? Number(top[sortColumn] ?? 0) : 0;
  const readout = sortedRows.length
    ? `${formatPivotLabel(config.aggregation)} ${config.valueField || config.binaryTarget || "records"} by ${rowLabel}${columnLabel ? ` and ${columnLabel}` : ""} is highest for ${topLabel} in the preview (${formatNumber(topValue)}). Review the full dataset before drawing production conclusions.`
    : "No pivot rows were generated from the current preview. Select fields with non-missing values.";
  return { config, columns: outputColumns, rows: sortedRows, readout };
}

function pivotGroupLabel(rows: Record<string, unknown>[], row: Record<string, unknown>, field: string, autoBin: boolean) {
  const raw = row[field];
  if (!autoBin || !isNumericColumn(rows, field)) return String(raw ?? "Missing");
  const values = numericValues(rows, field);
  const value = Number(raw);
  if (!Number.isFinite(value) || !values.length) return "Missing";
  const qs = [0, 0.2, 0.4, 0.6, 0.8, 1].map((q) => quantile(values, q));
  for (let i = 0; i < qs.length - 1; i++) {
    const lower = qs[i];
    const upper = qs[i + 1];
    if (value <= upper || i === qs.length - 2) return `Q${i + 1}: ${formatNumber(lower)} to ${formatNumber(upper)}`;
  }
  return "Missing";
}

function aggregateValues(values: number[], aggregation: string) {
  if (aggregation === "count") return values.length;
  if (!values.length) return 0;
  if (aggregation === "sum") return values.reduce((sum, value) => sum + value, 0);
  if (aggregation === "median") return quantile(values, 0.5);
  if (aggregation === "min") return Math.min(...values);
  if (aggregation === "max") return Math.max(...values);
  if (aggregation === "std dev" || aggregation === "std") return summarizeArray(values).std;
  return values.reduce((sum, value) => sum + value, 0) / values.length;
}

function formatPivotLabel(aggregation: string) {
  return aggregation === "event rate" ? "Event rate for" : aggregation;
}

function pythonAggregation(aggregation: string) {
  if (aggregation === "std dev") return "std";
  if (aggregation === "event rate") return "mean";
  return aggregation === "count" ? "count" : aggregation;
}

function pivotChartRows(result: PivotResult) {
  const metricColumn = result.columns[1];
  return result.rows.slice(0, 8).map((row) => ({ label: String(row[result.columns[0]] ?? "-"), value: Number(row[metricColumn] ?? 0) }));
}

function buildPythonTemplate(input: {
  dataset: DatasetSummary | null;
  versionId: string;
  rows: Record<string, unknown>[];
  columns: string[];
  target: string;
  groupColumn: string;
  metricColumn: string;
  secondaryDataset: DatasetSummary | null;
  secondaryVersionId: string;
  joinKey: string;
  joinType: string;
  pivot: PivotResult;
  businessQuestion?: string;
}) {
  const datasetName = input.dataset?.name ?? "selected_dataset";
  const lines = [
    "import pandas as pd",
    "",
    "# ATLAS Analytics Workbench Python template",
    `# Dataset: ${datasetName}`,
    `# Version: ${input.versionId || "not_selected"}`,
    "# Source: ATLAS Dataset Library preview/sample",
    `# Business question: ${input.businessQuestion || "not provided"}`,
    "",
    "try:",
    "    preview_rows",
    "except NameError:",
    "    preview_rows = []",
    "",
    "df = pd.DataFrame(preview_rows)",
    "print(\"ATLAS Analytics Workbench Python smoke test passed.\")",
    "print(df.shape)",
    "print(df.head())",
    "print(df.describe(include=\"all\"))",
  ];
  if (input.target) lines.push("", `print(df[${JSON.stringify(input.target)}].describe())`);
  if (input.groupColumn && input.metricColumn) lines.push("", `print(df.groupby(${JSON.stringify(input.groupColumn)})[${JSON.stringify(input.metricColumn)}].mean())`);
  if (input.pivot.config.rowField && input.pivot.config.valueField) {
    const rowField = input.pivot.config.rowField;
    const valueField = input.pivot.config.valueField;
    const bandName = `${rowField}_band`;
    const columnField = input.pivot.config.columnField;
    const columnBandName = columnField ? `${columnField}_band` : "";
    const groupField = input.pivot.config.autoBinRows ? bandName : rowField;
    const groupFields = columnField ? [groupField, input.pivot.config.autoBinColumns ? columnBandName : columnField] : [groupField];
    lines.push(
      "",
      "# Pivot Table Builder template",
      input.pivot.config.autoBinRows
        ? `df[${JSON.stringify(bandName)}] = pd.qcut(df[${JSON.stringify(rowField)}], q=5, duplicates="drop")`
        : `# Row field: ${rowField}`,
      columnField && input.pivot.config.autoBinColumns
        ? `df[${JSON.stringify(columnBandName)}] = pd.qcut(df[${JSON.stringify(columnField)}], q=5, duplicates="drop")`
        : columnField ? `# Column field: ${columnField}` : "# No pivot column field selected.",
      "pivot = (",
      groupFields.length > 1
        ? `    df.groupby(${JSON.stringify(groupFields)})[${JSON.stringify(valueField)}]`
        : `    df.groupby(${JSON.stringify(groupFields[0])})[${JSON.stringify(valueField)}]`,
      `    .${pythonAggregation(input.pivot.config.aggregation)}()`,
      "    .reset_index()",
      ")",
      "print(pivot)",
    );
  }
  lines.push("", "print(df.corr(numeric_only=True))");
  if (input.secondaryDataset && input.joinKey) {
    lines.push(
      "",
      "# Secondary dataset join template",
      "primary = pd.DataFrame(primary_preview_rows)",
      "secondary = pd.DataFrame(secondary_preview_rows)",
      input.joinType === "append/union"
        ? "joined = pd.concat([primary, secondary], ignore_index=True)"
        : `joined = primary.merge(secondary, how=${JSON.stringify(input.joinType)}, on=${JSON.stringify(input.joinKey)})`,
      "print(joined.shape)",
      "print(joined.head())",
    );
  }
  return lines.join("\n");
}

function buildSqlTemplate(input: {
  dataset: DatasetSummary | null;
  versionId: string;
  profile: DatasetProfile | null;
  columns: string[];
  target: string;
  secondaryDataset: DatasetSummary | null;
  secondaryVersionId: string;
  secondaryPreview: DatasetPreview | null;
  joinKey: string;
  joinType: string;
  pivot: PivotResult;
  businessQuestion?: string;
}) {
  const datasetName = input.dataset?.name ?? "selected_dataset";
  const table = executableTableName(datasetName);
  const logicalTable = logicalTableName(datasetName, input.versionId);
  const secondary = input.secondaryDataset ? executableTableName(input.secondaryDataset.name) : "";
  const secondaryLogical = input.secondaryDataset ? logicalTableName(input.secondaryDataset.name, input.secondaryVersionId) : "";
  const selectColumns = input.columns.length ? input.columns : input.profile?.schema?.map((column) => column.name) ?? ["*"];
  const header = [
    "-- ATLAS Analytics Workbench SQL template",
    `-- Dataset: ${datasetName}`,
    `-- Version: ${input.versionId || "not_selected"}`,
    `-- Rows: ${input.profile?.rowCount?.toLocaleString() ?? "unknown"}`,
    `-- Columns: ${input.profile?.columnCount?.toLocaleString() ?? selectColumns.length}`,
    `-- Logical ATLAS reference: ${logicalTable}`,
    `-- Business question: ${input.businessQuestion || "not provided"}`,
    "-- Runs against preview/sample rows loaded into local SQLite memory.",
    "",
  ];
  if (secondary && input.joinKey) {
    header.push(`-- Secondary logical ATLAS reference: ${secondaryLogical}`, "");
    const join = input.joinType === "append/union"
      ? [`SELECT * FROM ${table}`, "UNION ALL", `SELECT * FROM ${secondary};`]
      : [
          "SELECT",
          "    a.*,",
          "    b.*",
          `FROM ${table} a`,
          `${input.joinType.toUpperCase()} JOIN ${secondary} b`,
          `    ON a.${quoteSqlIdentifier(input.joinKey)} = b.${quoteSqlIdentifier(input.joinKey)};`,
        ];
    return header.concat(join).join("\n");
  }
  const baseSql = [
    "SELECT",
    selectColumns.map((column, index) => `    ${quoteSqlIdentifier(column)}${index < selectColumns.length - 1 ? "," : ""}`).join("\n"),
    `FROM ${table}`,
    "LIMIT 100;",
  ];
  if (!input.pivot.config.rowField || !input.pivot.config.valueField) return header.concat(baseSql).join("\n");
  const rowField = quoteSqlIdentifier(input.pivot.config.rowField);
  const rawRowField = input.pivot.config.rowField;
  const rawColumnField = input.pivot.config.columnField;
  const columnField = rawColumnField ? quoteSqlIdentifier(rawColumnField) : "";
  const valueField = quoteSqlIdentifier(input.pivot.config.valueField);
  const aggregate = sqlAggregation(input.pivot.config.aggregation, valueField);
  const aggregateAlias = quoteSqlIdentifier(`${input.pivot.config.aggregation.replace(/\s+/g, "_")}_${input.pivot.config.valueField}`);
  const selectFields = [
    input.pivot.config.autoBinRows ? `    ${rowField} AS pivot_row, -- Use NTILE/quantile banding in warehouse SQL for ${rawRowField}` : `    ${rowField} AS pivot_row,`,
    rawColumnField ? (input.pivot.config.autoBinColumns ? `    ${columnField} AS pivot_column, -- Use NTILE/quantile banding in warehouse SQL for ${rawColumnField}` : `    ${columnField} AS pivot_column,`) : "",
    `    ${aggregate} AS ${aggregateAlias},`,
    "    COUNT(*) AS n",
  ].filter(Boolean);
  const groupByFields = rawColumnField ? `${rowField}, ${columnField}` : rowField;
  const pivotSql = [
    "",
    "-- Pivot Table Builder template",
    "-- Numeric quantile row/column binning shown conceptually for SQL engines.",
    "-- Exact syntax depends on the SQL engine connected to ATLAS.",
    "SELECT",
    selectFields.join("\n"),
    `FROM ${table}`,
    `GROUP BY ${groupByFields}`,
    `ORDER BY ${aggregateAlias} DESC`,
    `LIMIT ${Math.max(3, Math.min(50, input.pivot.config.topN))};`,
  ];
  return header.concat(pivotSql).join("\n");
}

function sqlAggregation(aggregation: string, valueField: string) {
  if (aggregation === "count") return "COUNT(*)";
  if (aggregation === "std dev" || aggregation === "std") return `STDDEV(${valueField})`;
  if (aggregation === "event rate") return `AVG(${valueField})`;
  if (["sum", "mean", "median", "min", "max"].includes(aggregation)) {
    const fn = aggregation === "mean" ? "AVG" : aggregation.toUpperCase();
    return `${fn}(${valueField})`;
  }
  return `AVG(${valueField})`;
}

function buildRTemplate(input: {
  dataset: DatasetSummary | null;
  versionId: string;
  columns: string[];
  target: string;
  secondaryDataset: DatasetSummary | null;
  secondaryVersionId: string;
  joinKey: string;
  joinType: string;
  pivot: PivotResult;
  businessQuestion?: string;
}) {
  const datasetName = input.dataset?.name ?? "selected_dataset";
  const numericColumns = input.columns.slice(0, 12);
  const lines = [
    "# ATLAS Analytics Workbench R template",
    `# Dataset: ${datasetName}`,
    `# Version: ${input.versionId || "not_selected"}`,
    "# Source: ATLAS Dataset Library preview/sample",
    `# Business question: ${input.businessQuestion || "not provided"}`,
    "",
    "cat(\"ATLAS R smoke test passed.\\n\")",
    "cat(\"Rows:\", nrow(df), \" Columns:\", ncol(df), \"\\n\")",
    "print(head(df))",
    "summary(df)",
  ];
  if (input.target) lines.push("", `summary(df$${rName(input.target)})`);
  if (numericColumns.length >= 2) lines.push("", `cor(df$${rName(numericColumns[0])}, df$${rName(numericColumns[1])}, use = "complete.obs")`);
  if (input.pivot.config.rowField && input.pivot.config.valueField) {
    const rowField = input.pivot.config.rowField;
    const columnField = input.pivot.config.columnField;
    const valueField = input.pivot.config.valueField;
    const rowBand = `${rowField}_band`;
    const columnBand = columnField ? `${columnField}_band` : "";
    const grouping = [
      input.pivot.config.autoBinRows ? rowBand : rowField,
      columnField ? (input.pivot.config.autoBinColumns ? columnBand : columnField) : "",
    ].filter(Boolean).map(rName).join(", ");
    lines.push(
      "",
      "# Pivot Table Builder template",
      "library(dplyr)",
      "pivot <- df %>%",
      input.pivot.config.autoBinRows ? `  mutate(${rName(rowBand)} = dplyr::ntile(${rName(rowField)}, 5)) %>%` : `  # Row field: ${rowField}`,
      columnField && input.pivot.config.autoBinColumns ? `  mutate(${rName(columnBand)} = dplyr::ntile(${rName(columnField)}, 5)) %>%` : columnField ? `  # Column field: ${columnField}` : "  # No pivot column field selected.",
      `  group_by(${grouping}) %>%`,
      "  summarise(",
      `    ${rName(`${pythonAggregation(input.pivot.config.aggregation)}_${valueField}`)} = ${rAggregation(input.pivot.config.aggregation)}(${rName(valueField)}, na.rm = TRUE),`,
      "    n = dplyr::n(),",
      "    .groups = \"drop\"",
      "  )",
      "",
      "print(pivot)",
    );
  }
  if (input.secondaryDataset) {
    lines.push(
      "",
      "# Secondary dataset join template",
      "# primary_df and secondary_df should be loaded from the selected ATLAS datasets.",
      input.joinKey
        ? input.joinType === "append/union"
          ? "joined <- bind_rows(primary_df, secondary_df)"
          : `joined <- ${rJoin(input.joinType)}(primary_df, secondary_df, by = ${JSON.stringify(input.joinKey)})`
        : "# Select a join key to generate executable join code.",
      "print(dim(joined))",
      "head(joined)",
    );
  }
  return lines.join("\n");
}

function buildSasTemplate(input: {
  dataset: DatasetSummary | null;
  versionId: string;
  columns: string[];
  target: string;
  secondaryDataset: DatasetSummary | null;
  secondaryVersionId: string;
  joinKey: string;
  joinType: string;
  pivot: PivotResult;
  businessQuestion?: string;
}) {
  const datasetName = executableTableName(input.dataset?.name ?? "selected_dataset");
  const workTable = `work.${datasetName.toLowerCase()}`;
  const exportTable = `atlas.${datasetName}`;
  const secondaryName = input.secondaryDataset ? executableTableName(input.secondaryDataset.name) : "";
  const numericList = input.columns.slice(0, 12).join(" ") || "_numeric_";
  const lines = [
    "/* ATLAS Analytics Workbench SAS-Compatible template */",
    `/* Dataset: ${input.dataset?.name ?? "selected_dataset"} */`,
    `/* Version: ${input.versionId || "not_selected"} */`,
    "/* Mode: ATLAS SAS-Compatible, no SAS license required */",
    `/* Table available as: ${workTable} */`,
    "/* Source: ATLAS Dataset Library preview/sample */",
    `/* Business question: ${input.businessQuestion || "not provided"} */`,
    `/* Optional external export table name: ${exportTable} */`,
    "",
    `proc contents data=${workTable};`,
    "run;",
    "",
    `proc means data=${workTable} n mean median std min max;`,
    `    var ${numericList};`,
    "run;",
    "",
    `proc corr data=${workTable};`,
    `    var ${numericList};`,
    "run;",
    "",
    `proc print data=${workTable}(obs=10);`,
    "run;",
  ];
  if (input.pivot.config.rowField && input.pivot.config.valueField) {
    const rowField = input.pivot.config.rowField;
    const columnField = input.pivot.config.columnField;
    const classFields = [
      input.pivot.config.autoBinRows ? `${rowField}_band` : rowField,
      columnField ? (input.pivot.config.autoBinColumns ? `${columnField}_band` : columnField) : "",
    ].filter(Boolean).join(" ");
    lines.push(
      "",
      "/* Pivot-style summary */",
      input.pivot.config.autoBinRows || input.pivot.config.autoBinColumns
        ? `proc rank data=${workTable} groups=5 out=work.${datasetName.toLowerCase()}_binned;`
        : `data work.${datasetName.toLowerCase()}_binned; set ${workTable}; run;`,
    );
    if (input.pivot.config.autoBinRows || input.pivot.config.autoBinColumns) {
      lines.push(`    var ${[input.pivot.config.autoBinRows ? rowField : "", input.pivot.config.autoBinColumns ? columnField : ""].filter(Boolean).join(" ")};`);
      lines.push(`    ranks ${[input.pivot.config.autoBinRows ? `${rowField}_band` : "", input.pivot.config.autoBinColumns ? `${columnField}_band` : ""].filter(Boolean).join(" ")};`);
      lines.push("run;");
    }
    lines.push(
      "",
      `proc means data=work.${datasetName.toLowerCase()}_binned n mean median std;`,
      `    class ${classFields};`,
      `    var ${input.pivot.config.valueField};`,
      "run;",
    );
  }
  if (input.secondaryDataset) {
    lines.push(
      "",
      "/* Secondary dataset join template */",
      "proc sql;",
      input.joinKey
        ? input.joinType === "append/union"
          ? `    create table work.joined as select * from ${workTable} union all select * from work.${secondaryName.toLowerCase()};`
          : [
              "    create table work.joined as",
              "    select a.*, b.*",
              `    from ${workTable} as a`,
              `    ${sasJoin(input.joinType)} join work.${secondaryName.toLowerCase()} as b`,
              `        on a.${input.joinKey} = b.${input.joinKey};`,
            ].join("\n")
        : "    /* Select a join key to generate executable join code. */",
      "quit;",
    );
  }
  return lines.join("\n");
}

function rName(value: string) {
  return /^[A-Za-z.][A-Za-z0-9._]*$/.test(value) ? value : `\`${value.replace(/`/g, "")}\``;
}

function rAggregation(aggregation: string) {
  if (aggregation === "count") return "length";
  if (aggregation === "std dev" || aggregation === "std") return "sd";
  if (aggregation === "event rate") return "mean";
  return aggregation === "mean" ? "mean" : aggregation;
}

function rJoin(joinType: string) {
  if (joinType === "inner") return "inner_join";
  if (joinType === "right") return "right_join";
  if (joinType === "outer") return "full_join";
  return "left_join";
}

function sasJoin(joinType: string) {
  if (joinType === "inner") return "inner";
  if (joinType === "right") return "right";
  if (joinType === "outer") return "full";
  return "left";
}

function logicalTableName(name: string, versionId: string) {
  return `atlas_dataset.${sqlSafe(name)}_${sqlSafe(versionId || "current")}`;
}

function executableTableName(name: string) {
  return sqlSafe(name || "primary_dataset");
}

function sqlSafe(value: string) {
  return value.replace(/[^a-zA-Z0-9_]+/g, "_").replace(/^_+|_+$/g, "") || "dataset";
}

function quoteSqlIdentifier(value: string) {
  return /^[a-zA-Z_][a-zA-Z0-9_]*$/.test(value) ? value : `"${value.replace(/"/g, '""')}"`;
}

function copyText(text: string) {
  navigator.clipboard?.writeText(text).catch(() => undefined);
}

function exportInsight(payload: Record<string, unknown>) {
  const blob = new Blob([JSON.stringify(payload, null, 2)], { type: "application/json" });
  downloadBlob(blob, "atlas-analytics-insight.json");
}

function downloadBlob(blob: Blob, filename: string) {
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = filename;
  link.click();
  URL.revokeObjectURL(url);
}

function StatusPill({ label, value }: { label: string; value: string }) {
  return <div className="rounded-xl border border-white/15 bg-white/10 px-3 py-2"><div className="text-[10px] uppercase tracking-wide text-slate-300">{label}</div><div className="mt-1 max-w-[180px] truncate font-semibold text-white" title={value}>{value}</div></div>;
}

function ActionButton({ label, icon, onClick, variant = "primary" }: { label: string; icon: React.ReactNode; onClick: () => void; variant?: "primary" | "secondary" | "ghost" }) {
  const cls = variant === "primary" ? "bg-slate-950 text-white hover:bg-slate-800" : variant === "secondary" ? "border border-blue-200 bg-white text-blue-800 hover:bg-blue-50" : "border border-slate-300 bg-white text-slate-700 hover:bg-slate-50";
  return <button type="button" onClick={onClick} className={`inline-flex items-center gap-2 rounded-lg px-3 py-2 text-sm font-semibold shadow-sm ${cls}`}>{icon}{label}</button>;
}

function Metric({ label, value }: { label: string; value: string }) {
  return <div className="rounded-lg border border-slate-200 bg-white px-3 py-2"><div className="text-[11px] font-semibold uppercase text-slate-500">{label}</div><div className="mt-1 truncate text-lg font-semibold text-slate-950" title={value}>{value}</div></div>;
}

function PivotTable({ result }: { result: PivotResult }) {
  return (
    <div className="overflow-hidden rounded-xl border border-slate-200 bg-white shadow-sm">
      <div className="border-b border-slate-200 bg-slate-50 px-4 py-3">
        <div className="text-sm font-semibold text-slate-950">Pivot Result Table</div>
        <div className="mt-1 text-xs text-slate-500">Preview-based summary. Top-N and binning are applied in the browser.</div>
      </div>
      <div className="max-h-80 overflow-auto">
        <table className="min-w-full text-sm">
          <thead className="sticky top-0 bg-slate-100 text-xs uppercase tracking-wide text-slate-500">
            <tr>{result.columns.map((column) => <th key={column} className="border-b border-slate-200 px-3 py-2 text-left">{column}</th>)}</tr>
          </thead>
          <tbody>
            {result.rows.length ? result.rows.map((row, index) => (
              <tr key={`${row[result.columns[0]]}-${index}`} className={index % 2 ? "bg-slate-50/60" : "bg-white"}>
                {result.columns.map((column, columnIndex) => (
                  <td key={column} className={`border-b border-slate-100 px-3 py-2 ${columnIndex ? "text-right font-medium text-slate-900" : "max-w-[260px] text-slate-700"}`}>
                    {columnIndex ? formatNumber(Number(row[column] ?? 0)) : String(row[column] ?? "-")}
                  </td>
                ))}
              </tr>
            )) : (
              <tr>
                <td colSpan={result.columns.length} className="px-3 py-8 text-center text-sm text-slate-500">Select pivot fields to generate a preview table.</td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function SqlResultPanel({ result }: { result: AnalyticsSqlRunResult }) {
  const isSuccess = result.status === "success";
  return (
    <div className={`mt-4 rounded-xl border p-4 text-sm ${isSuccess ? "border-emerald-200 bg-emerald-50" : "border-rose-200 bg-rose-50"}`}>
      <div className="flex flex-wrap items-center justify-between gap-2 font-semibold">
        <span>{isSuccess ? "SQL preview completed" : "SQL preview blocked or failed"}</span>
        <span>{result.runtimeMs} ms - {result.rowCount.toLocaleString()} rows</span>
      </div>
      {!isSuccess && <div className="mt-3 rounded-lg border border-rose-200 bg-white p-3 text-rose-900">{result.error || "ATLAS could not run this SQL against preview rows."}</div>}
      {isSuccess && (
        <div className="mt-3 max-h-80 overflow-auto rounded-lg border border-slate-200 bg-white">
          <table className="min-w-full text-xs">
            <thead className="sticky top-0 bg-slate-100 uppercase tracking-wide text-slate-500">
              <tr>{result.columns.map((column) => <th key={column} className="border-b border-slate-200 px-3 py-2 text-left">{column}</th>)}</tr>
            </thead>
            <tbody>
              {result.rows.map((row, index) => (
                <tr key={index} className={index % 2 ? "bg-slate-50/70" : "bg-white"}>
                  {result.columns.map((column) => <td key={column} className="border-b border-slate-100 px-3 py-2 text-slate-800">{String(row[column] ?? "")}</td>)}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}

function Card({ title, icon, children }: { title: string; icon: React.ReactNode; children: React.ReactNode }) {
  return <section className="rounded-xl border border-slate-200 bg-white p-5 shadow-sm"><div className="flex items-center gap-2 text-slate-900">{icon}<h3 className="text-base font-semibold">{title}</h3></div><div className="mt-4 grid gap-3">{children}</div></section>;
}

function SummaryGrid({ items }: { items: Array<[string, string | number]> }) {
  return <div className="grid gap-2 sm:grid-cols-2">{items.map(([label, value]) => <Metric key={label} label={label} value={String(value)} />)}</div>;
}

function QualityList({ findings }: { findings: Array<{ label: string; detail: string; status: string }> }) {
  return <div className="grid gap-2">{findings.map((item) => <div key={`${item.label}-${item.detail}`} className={`rounded-lg border px-3 py-2 text-sm ${item.status === "pass" ? "border-emerald-200 bg-emerald-50 text-emerald-900" : item.status === "fail" ? "border-rose-200 bg-rose-50 text-rose-900" : "border-amber-200 bg-amber-50 text-amber-900"}`}><div className="font-semibold">{item.label}</div><div className="mt-1 text-xs leading-5">{item.detail}</div></div>)}</div>;
}

function NumericColumnView({ summary, values, column }: { summary: NumericSummary; values: number[]; column: string }) {
  return <div className="grid gap-3"><SummaryGrid items={[["Mean", summary.mean.toFixed(4)], ["Median", summary.median.toFixed(4)], ["Std dev", summary.std.toFixed(4)], ["Missing %", `${(summary.missingPct * 100).toFixed(2)}%`], ["P5", summary.p5.toFixed(4)], ["P95", summary.p95.toFixed(4)]]} /><Histogram values={values} title={`Histogram: ${column}`} /></div>;
}

function CategoricalColumnView({ rows, column }: { rows: Record<string, unknown>[]; column: string }) {
  const data = counts(rows, column);
  return <div><BarList rows={data.map(([label, value]) => ({ label, value }))} title={`Top Categories: ${column}`} /><p className="mt-2 text-xs text-slate-500">Shows the most frequent preview/sample categories.</p></div>;
}

function Histogram({ values, title }: { values: number[]; title: string }) {
  const min = Math.min(...values, 0);
  const max = Math.max(...values, 1);
  const bins = Array.from({ length: 12 }, (_, index) => ({ label: `${index + 1}`, value: 0 }));
  values.forEach((value) => {
    const idx = Math.min(11, Math.max(0, Math.floor(((value - min) / Math.max(0.000001, max - min)) * 12)));
    bins[idx].value += 1;
  });
  return <ChartFrame title={title} x="Value bins" y="Count"><BarList rows={bins.map((bin) => ({ label: bin.label, value: bin.value }))} compact /></ChartFrame>;
}

function BarList({ rows, title, compact = false }: { rows: Array<{ label: string; value: number }>; title?: string; compact?: boolean }) {
  const max = Math.max(...rows.map((row) => row.value), 1);
  return <div className="grid gap-2">{title && <div className="text-xs font-semibold uppercase text-slate-500">{title}</div>}{rows.map((row) => <div key={row.label} className="grid grid-cols-[110px_1fr_70px] items-center gap-2 text-xs"><div className="truncate" title={row.label}>{row.label}</div><div className={`rounded-full bg-slate-100 ${compact ? "h-2" : "h-3"}`}><div className="h-full rounded-full bg-blue-600" style={{ width: `${Math.max(3, (row.value / max) * 100)}%` }} /></div><div className="text-right font-semibold">{formatNumber(row.value)}</div></div>)}</div>;
}

function ChartFrame({ title, x, y, children }: { title: string; x: string; y: string; children: React.ReactNode }) {
  return <div className="rounded-lg border border-slate-200 bg-slate-50 p-3"><div className="font-semibold text-slate-950">{title}</div><div className="mt-2">{children}</div><div className="mt-2 flex justify-between text-[11px] font-medium text-slate-500"><span>X: {x}</span><span>Y: {y}</span></div></div>;
}

function TargetPanel({ target, summary }: { target: string; summary: { text: string; rankings: Array<{ feature: string; value: number }> } }) {
  if (!target) return <div className="rounded-lg border border-slate-200 bg-slate-50 p-3 text-sm text-slate-500">Select a target variable.</div>;
  return <div><p className="text-sm text-slate-600">{summary.text}</p><BarList rows={summary.rankings.map((row) => ({ label: row.feature, value: Math.abs(row.value) }))} title="Feature Relationship Ranking" /></div>;
}

function GroupComparison({ rows, metric }: { rows: Array<{ group: string; value: number; n: number }>; metric: string }) {
  return <ChartFrame title="Group Comparison Bar Chart" x="Group" y={metric}><BarList rows={rows.map((row) => ({ label: row.group, value: row.value }))} /><div className="mt-3 max-h-48 overflow-auto rounded border border-slate-200"><table className="min-w-full text-xs"><thead className="bg-slate-50"><tr><th className="px-2 py-1 text-left">Group</th><th className="px-2 py-1 text-right">N</th><th className="px-2 py-1 text-right">{metric}</th></tr></thead><tbody>{rows.map((row) => <tr key={row.group} className="border-t"><td className="px-2 py-1">{row.group}</td><td className="px-2 py-1 text-right">{row.n}</td><td className="px-2 py-1 text-right">{formatNumber(row.value)}</td></tr>)}</tbody></table></div></ChartFrame>;
}

function MiniCorrelation({ pairs }: { pairs: Array<{ a: string; b: string; corr: number }> }) {
  return <div>{pairs.length ? <BarList rows={pairs.map((pair) => ({ label: `${pair.a} x ${pair.b}`, value: Math.abs(pair.corr) }))} title="Top Absolute Correlations" /> : <div className="text-sm text-slate-500">At least two numeric fields are required.</div>}<p className="mt-2 text-xs text-slate-500">Shows strongest preview/sample numeric relationships.</p></div>;
}

function CodePanel(props: { title: string; generatedTitle: string; userTitle: string; generatedCode: string; userCode: string; setUserCode: (value: string) => void; onRun: () => void; onCopy: () => void; runLabel: string; disabled?: boolean; note: string }) {
  return (
    <section className="rounded-xl border border-slate-200 bg-white p-4 shadow-sm">
      <div className="flex items-center gap-2">
        <Code2 size={17} className="text-slate-700" />
        <h3 className="text-base font-semibold text-slate-950">{props.title}</h3>
      </div>
      <p className="mt-1 text-xs leading-5 text-slate-500">{props.note}</p>
      <div className="mt-3 grid gap-3">
        <div>
          <div className="text-xs font-semibold uppercase tracking-wide text-slate-500">{props.generatedTitle}</div>
          <pre className="mt-1 max-h-[260px] overflow-auto rounded-lg bg-slate-950 p-3 text-xs leading-5 text-slate-100">{props.generatedCode}</pre>
        </div>
        <div>
          <div className="text-xs font-semibold uppercase tracking-wide text-slate-500">{props.userTitle}</div>
          <textarea className="mt-1 h-[220px] w-full rounded-lg border border-slate-300 p-3 font-mono text-xs" value={props.userCode} onChange={(event) => props.setUserCode(event.target.value)} />
        </div>
      </div>
      <div className="mt-3 flex flex-wrap gap-2">
        <button type="button" onClick={props.onRun} disabled={props.disabled} className="inline-flex items-center gap-2 rounded-lg bg-slate-950 px-3 py-2 text-sm font-semibold text-white disabled:bg-slate-400"><Play size={15} /> {props.runLabel}</button>
        <button type="button" onClick={props.onCopy} className="inline-flex items-center gap-2 rounded-lg border border-slate-300 bg-white px-3 py-2 text-sm font-semibold text-slate-700"><Copy size={15} /> Copy Code</button>
      </div>
    </section>
  );
}

function OutputBlock({ title, text }: { title: string; text: string }) {
  return <div><div className="text-xs font-semibold uppercase tracking-wide text-slate-600">{title}</div><pre className="mt-1 max-h-52 overflow-auto rounded-lg bg-white p-3 text-xs leading-5 text-slate-900">{text}</pre></div>;
}

function cleanPythonStderr(stderr: string) {
  const text = (stderr || "").trim();
  if (!text) return "";
  if (text.includes("Failed checking if argv[0] is an import path entry") && text.includes("zipimport")) return "";
  const nonFatalPatterns = [
    "Failed checking if argv[0] is an import path entry",
    "KeyError:",
    "zipimport",
    "During handling of the above exception",
  ];
  const lines = text.split(/\r?\n/);
  const isOnlyBootstrapNoise = lines.every((line) => {
    const trimmed = line.trim();
    return !trimmed || nonFatalPatterns.some((pattern) => trimmed.includes(pattern)) || /^Traceback \(most recent call last\):$/.test(trimmed) || /^File "<frozen/.test(trimmed);
  });
  return isOnlyBootstrapNoise ? "" : text;
}

function formatNumber(value: number) {
  if (!Number.isFinite(value)) return "-";
  if (Math.abs(value) >= 1000) return value.toLocaleString(undefined, { maximumFractionDigits: 0 });
  return value.toLocaleString(undefined, { maximumFractionDigits: 3 });
}
