import React, { useEffect, useMemo, useRef, useState } from "react";
import {
  AlertTriangle,
  BarChart3,
  CheckCircle2,
  Database,
  Download,
  FileSearch,
  GitCompareArrows,
  LoaderCircle,
  RefreshCw,
  Save,
  Search,
  ShieldCheck,
  Target,
} from "lucide-react";
import type { LucideIcon } from "lucide-react";
import StepShell from "../components/StepShell";
import {
  AtlasAttentionPanel,
  AtlasDataScopeBadge,
  AtlasWorkflowSection,
  type AtlasWorkflowMetric,
} from "../components/ui/AtlasWorkflow";
import { createEvidence } from "../lib/evidenceGraph";
import { logDecision } from "../lib/decisionJournal";
import { loadLocalDataset } from "../lib/localDataset";
import { useWorkflowStore } from "../state/useWorkflowStore";
import { formatNullableMetric, getDatasetScopeLabel, safeArray, safeObject } from "../lib/workflowSafety";
import VisualAnalysisPanel from "../visual-intelligence/production/VisualAnalysisPanel";
import DistributionExplorer from "../visual-intelligence/prototypes/DistributionExplorer";
import TargetIntelligenceWorkspace from "../components/eda/TargetIntelligenceWorkspace";
import type { PredictorOption } from "../components/eda/TargetByPredictorPanel";

const API_BASE =
  (import.meta.env.VITE_API_BASE as string | undefined)?.replace(/\/$/, "") ||
  "http://127.0.0.1:8001/api";

const FINDINGS_KEY = "atlas-predictive-eda-findings-v2";

type EDATab = "overview" | "target" | "predictors" | "relationships" | "stability" | "findings";
type Scope = "full_dataset" | "complete_browser_dataset" | "preview_profile" | "rendered_sample" | "training_pipeline" | "unavailable";

type WorkspaceResponse = {
  ok: boolean;
  section: EDATab;
  scope: Scope;
  row_count: number;
  column_count: number;
  target: string;
  problem_type: "classification" | "regression";
  event_value?: unknown;
  dataset_version: string;
  duration_ms: number;
  cache_status: "hit" | "miss";
  [key: string]: any;
};

type FindingsState = {
  commentary: string;
  status: "draft" | "reviewed" | "accepted";
  savedAt?: string;
};

type EDAErrorState = {
  message: string;
  endpoint: string;
  status?: number;
  code?: string;
  recovery?: string;
  technical?: string;
};

type HistogramFetchState = {
  feature: string;
  requestedBins: number;
  bins: Array<{ bin: number; lower: number; upper: number; count: number }>;
  rowCount?: number;
  loading: boolean;
  error?: string;
};

const tabs: Array<{ id: EDATab; label: string; icon: LucideIcon }> = [
  { id: "overview", label: "Overview", icon: Database },
  { id: "target", label: "Target", icon: Target },
  { id: "predictors", label: "Predictors", icon: BarChart3 },
  { id: "relationships", label: "Relationships", icon: GitCompareArrows },
  { id: "stability", label: "Stability & Segments", icon: ShieldCheck },
  { id: "findings", label: "Findings", icon: FileSearch },
];

function readFindings(): FindingsState {
  try {
    const parsed = JSON.parse(localStorage.getItem(FINDINGS_KEY) || "null");
    if (parsed && typeof parsed.commentary === "string") return parsed;
  } catch {
    // Invalid prior browser state should not block governed backend analysis.
  }
  return { commentary: "", status: "draft" };
}

function formatNumber(value: unknown, digits = 2) {
  return formatNullableMetric(value, digits, "Not evaluated");
}

function formatPercent(value: unknown, digits = 2) {
  const number = Number(value);
  if (!Number.isFinite(number)) return "Not available";
  return `${(number * 100).toLocaleString(undefined, { maximumFractionDigits: digits })}%`;
}

function downloadCsv(filename: string, rows: Record<string, unknown>[]) {
  if (!rows.length) return;
  const headers = Array.from(new Set(rows.flatMap((row) => Object.keys(row))));
  const escape = (value: unknown) => `"${String(value ?? "").replace(/"/g, '""')}"`;
  const text = [headers.map(escape).join(","), ...rows.map((row) => headers.map((header) => escape(row[header])).join(","))].join("\n");
  const url = URL.createObjectURL(new Blob([text], { type: "text/csv;charset=utf-8" }));
  const link = document.createElement("a");
  link.href = url;
  link.download = filename;
  link.click();
  URL.revokeObjectURL(url);
}

export default function Step02EDA() {
  const projectId = useWorkflowStore((state) => state.projectId);
  const projectName = useWorkflowStore((state) => state.projectName);
  const getNextStepPath = useWorkflowStore((state) => state.getNextStepPath);
  const [activeTab, setActiveTab] = useState<EDATab>("overview");
  const [sections, setSections] = useState<Partial<Record<EDATab, WorkspaceResponse>>>({});
  const [loading, setLoading] = useState<EDATab | null>(null);
  const [error, setError] = useState<EDAErrorState | null>(null);
  const [segmentField, setSegmentField] = useState("");
  const [dateField, setDateField] = useState("");
  const [pairwiseFeatures, setPairwiseFeatures] = useState<string[]>([]);
  const [histogramBins, setHistogramBins] = useState(20);
  const [findings, setFindings] = useState<FindingsState>(readFindings);
  const [evidenceMessage, setEvidenceMessage] = useState("");
  const requestSequence = useRef<Partial<Record<EDATab, number>>>({});
  const confirmedDataset = useMemo(() => loadLocalDataset(), []);

  const overview = sections.overview;
  const available = overview?.available_fields ?? {};

  // Target Intelligence inputs. The predictor list comes from the governed
  // overview field inventory; IV is only attached when the Predictors section
  // has already computed it, so the Target tab never triggers a second IV pass.
  const predictorOptions: PredictorOption[] = useMemo(() => {
    const ivByFeature = new Map<string, number | null>();
    for (const row of safeArray<any>(sections.predictors?.numeric)) ivByFeature.set(String(row.feature), row.iv ?? null);
    for (const row of safeArray<any>(sections.predictors?.categorical)) ivByFeature.set(String(row.feature), row.iv ?? null);
    const numeric: PredictorOption[] = (available.numeric ?? []).map((feature: string) => ({
      feature,
      kind: "numeric" as const,
      iv: ivByFeature.get(feature) ?? null,
    }));
    const categorical: PredictorOption[] = (available.categorical ?? []).map((feature: string) => ({
      feature,
      kind: "categorical" as const,
      iv: ivByFeature.get(feature) ?? null,
    }));
    return [...numeric, ...categorical].filter((item) => item.feature !== overview?.target);
  }, [available.numeric, available.categorical, sections.predictors, overview?.target]);

  const datasetIdentity = useMemo(() => {
    const library = confirmedDataset?.dataset_library;
    if (!library?.datasetId || !library?.versionId) return null;
    return {
      datasetId: library.datasetId,
      versionId: library.versionId,
      datasetName: library.datasetName ?? "",
    };
  }, [confirmedDataset?.dataset_library]);
  const requestBody = useMemo(
    () => ({
      project_id: projectId,
      target: overview?.target || confirmedDataset?.target || undefined,
      event_value: overview?.event_value,
      problem_type: overview?.problem_type,
      selected_features: confirmedDataset?.selected_columns ?? [],
      pairwise_features: pairwiseFeatures,
      segment_field: segmentField || undefined,
      date_field: dateField || undefined,
      histogram_bins: histogramBins,
      rendered_sample_limit: 5000,
    }),
    [confirmedDataset?.selected_columns, confirmedDataset?.target, dateField, histogramBins, overview?.event_value, overview?.problem_type, overview?.target, pairwiseFeatures, projectId, segmentField],
  );

  async function loadSection(section: EDATab, force = false, overrides: Record<string, unknown> = {}) {
    if (!force && sections[section]) return;
    const endpoint = `${API_BASE}/eda/workspace/${section}`;
    const sequence = (requestSequence.current[section] ?? 0) + 1;
    requestSequence.current[section] = sequence;
    setLoading(section);
    setError(null);
    try {
      const response = await fetch(endpoint, {
        method: "POST",
        credentials: "include",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ ...requestBody, ...overrides }),
      });
      const payload = await response.json().catch(() => null);
      if (requestSequence.current[section] !== sequence) return;
      if (!response.ok || !payload?.ok) {
        const detail = safeObject(payload?.detail);
        setError({
          endpoint,
          status: response.status,
          code: String(detail.code ?? payload?.code ?? (response.status === 404 ? "eda_route_unavailable" : "eda_request_failed")),
          message: String(
            detail.message ??
              payload?.message ??
              payload?.error ??
              (response.status === 404 ? "EDA service route is unavailable. Confirm the FastAPI backend includes the EDA router." : `EDA ${section} analysis failed.`),
          ),
          recovery: String(detail.recovery ?? "Return to Data Acquisition and re-register the dataset, or retry after confirming the backend is running."),
          technical: JSON.stringify(payload ?? { status: response.status }, null, 2),
        });
        return;
      }
      setSections((current) => ({ ...current, [section]: payload as WorkspaceResponse }));
    } catch (cause) {
      if (requestSequence.current[section] !== sequence) return;
      setError({
        endpoint,
        code: "eda_backend_unavailable",
        message: cause instanceof Error ? cause.message : "ATLAS could not load this EDA section.",
        recovery: "Confirm the FastAPI backend is running, then retry. If the backend restarted, return to Data Acquisition and re-register the dataset.",
      });
    } finally {
      if (requestSequence.current[section] === sequence) setLoading(null);
    }
  }

  useEffect(() => {
    void loadSection("overview");
    // Load once from the governed backend. Secondary sections remain lazy.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    if (activeTab !== "overview") void loadSection(activeTab);
    // Configuration-specific refreshes are handled by explicit actions below.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [activeTab]);

  async function refreshActiveSection(overrides: Record<string, unknown> = {}) {
    await loadSection(activeTab, true, overrides);
  }

  async function saveEvidence() {
    const findingsPayload = sections.findings;
    if (!overview || !findingsPayload) {
      setEvidenceMessage("Open the Findings tab before saving governed EDA evidence.");
      return;
    }
    setEvidenceMessage("Saving evidence...");
    try {
      await createEvidence({
        projectId,
        projectName,
        evidenceType: "eda",
        title: "Governed Exploratory Data Analysis",
        summary: `Full-dataset EDA for ${overview.target} across ${overview.row_count.toLocaleString()} registered rows.`,
        sourcePage: "Exploratory Data Analysis",
        sourceRoute: "/step02",
        datasetIds: [overview.dataset_version],
        modelIds: [],
        documentIds: [],
        notebookIds: [],
        supportsSections: ["Exploratory Data Analysis", "Data Quality", "Feature Engineering"],
        tags: ["predictive_modeling", "eda", "full_dataset"],
        status: findings.status === "accepted" ? "ready" : "needs_review",
        importance: "high",
        lineage: {
          datasetVersion: overview.dataset_version,
          target: overview.target,
          problemType: overview.problem_type,
          eventValue: overview.event_value,
          rowCount: overview.row_count,
          scope: overview.scope,
        },
        payload: {
          headline: overview.headline,
          findings: findingsPayload.findings,
          carryForward: findingsPayload.carry_forward,
          userCommentary: findings.commentary,
          findingStatus: findings.status,
        },
      });
      const next = { ...findings, savedAt: new Date().toISOString() };
      localStorage.setItem(FINDINGS_KEY, JSON.stringify(next));
      setFindings(next);
      setEvidenceMessage("EDA evidence saved.");
    } catch (cause) {
      setEvidenceMessage(cause instanceof Error ? cause.message : "EDA evidence could not be saved.");
    }
  }

  async function completeEDA() {
    localStorage.setItem(FINDINGS_KEY, JSON.stringify(findings));
    logDecision({
      workflowStep: "Exploratory Data Analysis",
      actionType: "workflow_setting_changed",
      subject: "EDA findings status",
      previousValue: "draft",
      newValue: findings.status,
      systemRecommendation: "Review full-dataset findings and document any downstream treatment decisions.",
      userReason: findings.commentary,
    });
    if (sections.findings && findings.commentary.trim()) await saveEvidence();
  }

  const heroMetrics: AtlasWorkflowMetric[] = overview
    ? [
        { label: "Dataset Scope", value: getDatasetScopeLabel(overview.scope), tone: "info" },
        { label: "Registered Rows", value: overview.row_count.toLocaleString() },
        { label: "Target", value: overview.target },
        { label: "Problem Type", value: titleCase(overview.problem_type) },
        { label: "Predictors", value: formatNumber(overview.headline?.predictors, 0) },
        { label: "Analysis State", value: "Available", tone: "success" },
      ]
    : [{ label: "Analysis State", value: loading ? "Loading full profile" : error ? "Analysis failed" : "Backend dataset missing", tone: loading ? "info" : "warning" }];

  const activeData = sections[activeTab];

  return (
    <StepShell
      title="Step 2: Exploratory Data Analysis"
      subtitle="Examine the full modeling population, target behavior, predictor quality, relationships, stability, segments, and governed findings before treatment decisions."
      variant="analysis"
      heroMetrics={heroMetrics}
      nextPath={getNextStepPath("step02")}
      nextDisabled={!overview || !!loading}
      nextDisabledReason={!overview ? "Load the full registered dataset before completing EDA." : "Wait for the active analysis to complete."}
      nextLabel="Confirm EDA and Continue"
      onNext={completeEDA}
      nextStatusLine="Record the reviewed EDA state and continue to outlier treatment."
    >
      <div className="space-y-4">
        <div className="atlas-workflow-section atlas-workflow-section--analysis p-2">
          <div className="flex flex-col gap-2 xl:flex-row xl:items-center xl:justify-between">
            <div className="flex min-w-0 gap-1 overflow-x-auto" role="tablist" aria-label="EDA analysis sections">
              {tabs.map((tab) => {
                const Icon = tab.icon;
                const selected = activeTab === tab.id;
                return (
                  <button
                    key={tab.id}
                    type="button"
                    role="tab"
                    aria-selected={selected}
                    className={[
                      "atlas-tab-button shrink-0 gap-2 border",
                      selected
                        ? "atlas-tab-button-active border-blue-600"
                        : "atlas-tab-button-inactive border-slate-200 bg-white shadow-sm",
                    ].join(" ")}
                    onClick={() => setActiveTab(tab.id)}
                  >
                    <Icon size={15} />
                    {tab.label}
                  </button>
                );
              })}
            </div>
            <div className="flex shrink-0 items-center gap-2 px-2">
              {activeData ? <AtlasDataScopeBadge scope={activeData.scope} rows={activeData.row_count} /> : null}
              <button type="button" className="atlas-secondary-button" onClick={() => void refreshActiveSection()} disabled={!!loading}>
                <RefreshCw size={15} className={loading === activeTab ? "animate-spin" : ""} />
                Refresh
              </button>
            </div>
          </div>
        </div>

        {error ? (
          <EDAUnavailablePanel error={error} onRetry={() => void refreshActiveSection()} />
        ) : null}

        {loading === activeTab && !activeData ? <LoadingPanel label={`Running ${tabs.find((tab) => tab.id === activeTab)?.label} analysis`} /> : null}

        {activeTab === "overview" && overview ? <OverviewPanel data={overview} /> : null}
        {!loading && !error && !activeData ? (
          <AtlasAttentionPanel title="EDA section not loaded" tone="info">
            This section has not returned profile data yet. Use Refresh to retry the governed backend request.
          </AtlasAttentionPanel>
        ) : null}
        {activeTab === "target" && activeData ? (
          <TargetIntelligenceWorkspace
            data={activeData}
            projectId={projectId}
            projectName={projectName}
            datasetIdentity={datasetIdentity}
            eventValue={activeData.event_value ?? confirmedDataset?.event_value}
            nonEventValue={confirmedDataset?.non_event_value}
            predictorOptions={predictorOptions}
            timeField={dateField}
            segmentField={segmentField}
            segmentCandidates={available.segment_candidates ?? []}
            onTimeField={(value) => {
              setDateField(value);
              void refreshActiveSection({ date_field: value || undefined });
            }}
            onSegmentField={(value) => {
              setSegmentField(value);
              void refreshActiveSection({ segment_field: value || undefined });
            }}
            onRunConditional={() => void refreshActiveSection()}
          />
        ) : null}
        {activeTab === "predictors" && activeData ? (
          <PredictorsPanel
            data={activeData}
            histogramBins={histogramBins}
            onHistogramBins={setHistogramBins}
            projectId={projectId}
          />
        ) : null}
        {activeTab === "relationships" && activeData ? (
          <RelationshipsPanel
            data={activeData}
            numericFields={available.numeric ?? []}
            pairwiseFeatures={pairwiseFeatures}
            onPairwiseFeatures={setPairwiseFeatures}
            onRun={() => void refreshActiveSection()}
          />
        ) : null}
        {activeTab === "stability" && activeData ? (
          <StabilityPanel
            data={activeData}
            dateFields={available.date_candidates ?? []}
            segmentFields={available.segment_candidates ?? []}
            dateField={dateField}
            segmentField={segmentField}
            onDateField={setDateField}
            onSegmentField={setSegmentField}
            onRun={() => void refreshActiveSection()}
          />
        ) : null}
        {activeTab === "findings" && activeData ? (
          <FindingsPanel
            data={activeData}
            state={findings}
            onChange={(next) => {
              setFindings(next);
              localStorage.setItem(FINDINGS_KEY, JSON.stringify(next));
            }}
            onSave={() => void saveEvidence()}
            message={evidenceMessage}
          />
        ) : null}
      </div>
    </StepShell>
  );
}

function EDAUnavailablePanel({ error, onRetry }: { error: EDAErrorState; onRetry: () => void }) {
  const routeMissing = error.status === 404 || error.code === "eda_route_unavailable";
  return (
    <AtlasAttentionPanel title={routeMissing ? "EDA service route is unavailable" : "Full EDA profile is unavailable"} tone="danger">
      <div className="space-y-3">
        <p>
          {routeMissing
            ? "Confirm the FastAPI backend includes the EDA router."
            : "ATLAS could not find the registered backend dataset for this project. Return to Data Acquisition and re-register the dataset, or retry after confirming the backend is running."}
        </p>
        <div className="rounded-lg border border-red-200 bg-white p-3 text-sm text-red-950">
          <div><strong>What failed:</strong> {error.message}</div>
          <div><strong>Endpoint:</strong> {error.endpoint}</div>
          <div><strong>Status:</strong> {error.status ?? "No response"}</div>
          <div><strong>Recovery:</strong> {error.recovery}</div>
        </div>
        <div className="flex flex-wrap gap-2">
          <button type="button" className="atlas-primary-button" onClick={onRetry}>
            <RefreshCw size={15} /> Retry
          </button>
          <a className="atlas-secondary-button" href="/step01">Go to Data Acquisition</a>
        </div>
        {error.technical ? (
          <details className="rounded-lg border border-red-200 bg-white p-3">
            <summary className="cursor-pointer text-sm font-semibold text-red-950">Technical details</summary>
            <pre className="mt-2 max-h-64 overflow-auto whitespace-pre-wrap text-xs text-slate-700">{error.technical}</pre>
          </details>
        ) : null}
      </div>
    </AtlasAttentionPanel>
  );
}

function LoadingPanel({ label }: { label: string }) {
  return (
    <div className="atlas-workflow-section flex min-h-52 items-center justify-center">
      <div className="text-center text-slate-600">
        <LoaderCircle size={28} className="mx-auto animate-spin text-blue-600" />
        <div className="mt-3 font-semibold text-slate-900">{label}</div>
        <div className="mt-1 text-sm">ATLAS is aggregating the governed backend dataset.</div>
      </div>
    </div>
  );
}

function OverviewPanel({ data }: { data: WorkspaceResponse }) {
  const headline = safeObject(data.headline);
  const integrity = safeObject(data.data_integrity);
  const target = safeObject(data.target_profile);
  const constantColumns = safeArray(integrity.constant_columns);
  const identifierCandidates = safeArray(integrity.identifier_candidates);
  const leakageCandidates = safeArray(integrity.leakage_candidates);
  return (
    <div className="space-y-4">
      <AtlasWorkflowSection eyebrow="Governed population" title="Modeling Dataset Overview" description="Headline metrics are aggregated from the full backend dataset and are independent of browser preview settings." tone="info">
        <MetricGrid
          items={[
            ["Registered rows", formatNumber(headline.rows, 0)],
            ["Predictors", formatNumber(headline.predictors, 0)],
            ["Numeric", formatNumber(headline.numeric_predictors, 0)],
            ["Categorical", formatNumber(headline.categorical_predictors, 0)],
            ["Missing cells", formatNumber(headline.missing_cells, 0)],
            ["Duplicate rows", formatNumber(headline.duplicate_rows, 0)],
          ]}
        />
      </AtlasWorkflowSection>
      <div className="grid gap-4 xl:grid-cols-[1.05fr_0.95fr]">
        <AtlasWorkflowSection eyebrow="Outcome" title="Target Readiness" tone={target.rare_event ? "warning" : "info"}>
          <MetricGrid
            items={data.problem_type === "classification"
              ? [
                  ["Event count", formatNumber(target.event_count, 0)],
                  ["Non-event count", formatNumber(target.non_event_count, 0)],
                  ["Event rate", formatPercent(target.event_rate, 3)],
                  ["Missing target", formatNumber(target.missing_count, 0)],
                ]
              : [
                  ["Valid target", formatNumber(target.valid_count, 0)],
                  ["Mean", formatNumber(target.mean)],
                  ["Std. deviation", formatNumber(target.standard_deviation)],
                  ["Missing target", formatNumber(target.missing_count, 0)],
                ]}
          />
          {data.problem_type === "classification" ? (
            <div className="mt-4">
              <ClassDistributionChart rows={safeArray<any>(target.class_distribution)} scope="Full Dataset Aggregation" />
            </div>
          ) : (
            <div className="mt-4">
              <HistogramChart bins={chartBins(target)} source={target} scope="Full Dataset Aggregation" />
            </div>
          )}
          {target.rare_event ? <p className="mt-3 text-sm text-amber-900">Rare-event safeguards are required. Accuracy is not an appropriate primary metric for this target distribution.</p> : null}
        </AtlasWorkflowSection>
        <AtlasWorkflowSection eyebrow="Integrity" title="Review Signals" tone={leakageCandidates.length ? "warning" : "neutral"}>
          <StatusList
            items={[
              { label: "Duplicate records", value: integrity.duplicate_rows ? `${formatNumber(integrity.duplicate_rows, 0)} detected` : "None detected", warning: !!integrity.duplicate_rows },
              { label: "Constant fields", value: `${constantColumns.length} detected`, warning: !!constantColumns.length },
              { label: "Identifier candidates", value: `${identifierCandidates.length} require review`, warning: !!identifierCandidates.length },
              { label: "Leakage-name candidates", value: `${leakageCandidates.length} require evidence review`, warning: !!leakageCandidates.length },
            ]}
          />
        </AtlasWorkflowSection>
      </div>
    </div>
  );
}

function PredictorsPanel({
  data,
  histogramBins,
  onHistogramBins,
  projectId,
}: {
  data: WorkspaceResponse;
  histogramBins: number;
  onHistogramBins: (value: number) => void;
  projectId: string;
}) {
  const [search, setSearch] = useState("");
  const [sortMode, setSortMode] = useState("signal");
  const [rowLimit, setRowLimit] = useState(15);
  const allNumeric = safeArray<any>(data.numeric);
  const allCategorical = safeArray<any>(data.categorical);
  const [selectedFeature, setSelectedFeature] = useState(() => String(allNumeric[0]?.feature ?? allCategorical[0]?.feature ?? ""));
  const signalKey = data.problem_type === "classification" ? "iv" : "correlation_with_target";
  const sortRows = (rows: any[]) => [...rows].sort((left, right) => {
    if (sortMode === "name") return String(left.feature ?? "").localeCompare(String(right.feature ?? ""));
    const key = sortMode === "missing" ? "missing_rate" : sortMode === "outliers" ? "outlier_rate" : signalKey;
    return Math.abs(Number(right?.[key] ?? 0)) - Math.abs(Number(left?.[key] ?? 0));
  });
  // EDA-UX-004: the inventory tables are filtered by the shared "Search
  // predictors" box. Typing a feature name to locate it legitimately reduces the
  // table to one row, but the section still claimed to be the full inventory
  // with no result count and no sign that a filter was active -- so it read as
  // "the inventory collapsed to the selected predictor". Matched/total counts and
  // an explicit filter notice are now surfaced for each table.
  const numericMatches = sortRows(safeArray<any>(data.numeric).filter((row: any) => String(row.feature).toLowerCase().includes(search.toLowerCase())));
  const categoricalMatches = sortRows(safeArray<any>(data.categorical).filter((row: any) => String(row.feature).toLowerCase().includes(search.toLowerCase())));
  const missingMatches = sortRows(safeArray<any>(data.missingness).filter((row: any) => row.missing_count > 0));
  const numeric = numericMatches.slice(0, rowLimit);
  const categorical = categoricalMatches.slice(0, rowLimit);
  const missing = missingMatches.slice(0, rowLimit);
  const searchActive = Boolean(search.trim());
  const selected =
    allNumeric.find((row: any) => row.feature === selectedFeature) ??
    allCategorical.find((row: any) => row.feature === selectedFeature) ??
    allNumeric[0] ??
    allCategorical[0];
  const selectedIsNumeric = !!allNumeric.find((row: any) => row.feature === selected?.feature);
  const selectedName = String(selected?.feature ?? "");
  const [histogramReload, setHistogramReload] = useState(0);
  const [histogramState, setHistogramState] = useState<HistogramFetchState>({
    feature: "",
    requestedBins: histogramBins,
    bins: [],
    loading: false,
  });
  const histogramSequence = useRef(0);

  useEffect(() => {
    if (!selectedIsNumeric || !selectedName) {
      setHistogramState({ feature: selectedName, requestedBins: histogramBins, bins: [], loading: false });
      return;
    }
    const sequence = histogramSequence.current + 1;
    histogramSequence.current = sequence;
    const controller = new AbortController();
    setHistogramState((current) => ({
      feature: selectedName,
      requestedBins: histogramBins,
      bins: current.feature === selectedName && current.requestedBins === histogramBins ? current.bins : [],
      rowCount: current.feature === selectedName ? current.rowCount : undefined,
      loading: true,
      error: undefined,
    }));

    void fetch(`${API_BASE}/eda/histogram/${encodeURIComponent(selectedName)}?bins=${histogramBins}&project_id=${encodeURIComponent(projectId)}`, {
      credentials: "include",
      signal: controller.signal,
    })
      .then(async (response) => {
        const payload = await response.json().catch(() => null);
        if (!response.ok || !payload?.ok) throw new Error(String(payload?.detail?.message ?? payload?.detail ?? payload?.error ?? "Histogram aggregation failed."));
        const edges = safeArray<number>(payload.edges).map(Number);
        const counts = safeArray<number>(payload.counts).map(Number);
        if (!counts.length || edges.length !== counts.length + 1) throw new Error("The histogram service returned an incomplete bin contract.");
        return {
          feature: selectedName,
          requestedBins: histogramBins,
          bins: counts.map((count, index) => ({ bin: index + 1, lower: edges[index], upper: edges[index + 1], count })),
          rowCount: Number(payload.row_count),
          loading: false,
        } satisfies HistogramFetchState;
      })
      .then((next) => {
        if (histogramSequence.current === sequence) setHistogramState(next);
      })
      .catch((cause) => {
        if (controller.signal.aborted || histogramSequence.current !== sequence) return;
        setHistogramState({
          feature: selectedName,
          requestedBins: histogramBins,
          bins: [],
          loading: false,
          error: cause instanceof Error ? cause.message : "Histogram aggregation failed.",
        });
      });

    return () => controller.abort();
  }, [data.dataset_version, histogramBins, histogramReload, selectedIsNumeric, selectedName]);

  const profileBins = chartBins(selected);
  const dedicatedHistogramCurrent = histogramState.feature === selectedName && histogramState.requestedBins === histogramBins;
  const resolvedHistogram = dedicatedHistogramCurrent && histogramState.bins.length
    ? histogramState.bins
    : profileBins.length === histogramBins
      ? profileBins
      : [];
  const histogramPending = selectedIsNumeric && (!dedicatedHistogramCurrent || histogramState.loading);
  return (
    <div className="space-y-4">
      {/* EDA-PREDICTORS-001: the instructional block (heading, explanatory
          paragraph, and four-step workflow) was removed at James's request --
          it did not perform an analytical function. Not replaced with another
          instructional card; the controls below are self-describing. */}
      <AtlasWorkflowSection
        eyebrow="Predictors"
        title="Predictor Inventory and Investigation"
        description="Full-dataset numeric, categorical, and missingness diagnostics. Treatment remains on later workflow steps."
        tone="info"
        action={<AtlasDataScopeBadge scope="full_dataset" rows={data.row_count} />}
      >
        <div className="flex flex-col gap-3 xl:flex-row xl:items-center xl:justify-between">
          <label className="relative block max-w-sm flex-1">
            <Search size={15} className="pointer-events-none absolute left-3 top-2.5 text-slate-400" />
            <input className="atlas-input pl-9" value={search} onChange={(event) => setSearch(event.target.value)} placeholder="Search predictors" />
          </label>
          <div className="grid gap-2 sm:grid-cols-[180px_150px_auto]">
            <label>
              <span className="sr-only">Sort predictor profile</span>
              <select className="atlas-input" value={sortMode} onChange={(event) => setSortMode(event.target.value)}>
                <option value="signal">Sort by target signal</option>
                <option value="missing">Sort by missingness</option>
                <option value="outliers">Sort by outliers</option>
                <option value="name">Sort by feature name</option>
              </select>
            </label>
            <label>
              <span className="sr-only">Profile row count</span>
              <select className="atlas-input" value={rowLimit} onChange={(event) => setRowLimit(Number(event.target.value))}>
                {[10, 15, 25, 50, 100].map((value) => <option key={value} value={value}>Show {value}</option>)}
              </select>
            </label>
            <button type="button" className="atlas-secondary-button" onClick={() => downloadCsv("atlas-eda-predictors.csv", [...numeric, ...categorical])}>
              <Download size={15} /> Download profile CSV
            </button>
          </div>
        </div>
      </AtlasWorkflowSection>
      <AtlasWorkflowSection eyebrow="Feature investigation" title="Selected Predictor Visualization" description="Charts use backend aggregated bins or bounded backend-rendered summaries. They do not compute full-dataset chart data in the browser." tone="info">
        <div className="grid gap-4 lg:grid-cols-[280px_1fr]">
          <div className="space-y-3">
            <label>
              <span className="atlas-label">Feature selector</span>
              <select className="atlas-input mt-1" value={selected?.feature ?? ""} onChange={(event) => setSelectedFeature(event.target.value)}>
                {allNumeric.length ? <optgroup label="Numeric predictors">{allNumeric.map((row: any) => <option key={row.feature} value={row.feature}>{row.feature}</option>)}</optgroup> : null}
                {allCategorical.length ? <optgroup label="Categorical predictors">{allCategorical.map((row: any) => <option key={row.feature} value={row.feature}>{row.feature}</option>)}</optgroup> : null}
              </select>
              <span className="mt-1 block text-xs text-slate-500">Chart scope: Full Dataset Aggregation</span>
            </label>
            <label>
              <span className="atlas-label">Histogram bins</span>
              <select className="atlas-input mt-1" value={histogramBins} onChange={(event) => onHistogramBins(Number(event.target.value))}>
                {[10, 15, 20, 30, 40, 50, 60].map((value) => (
                  <option key={value} value={value}>{value} bins</option>
                ))}
              </select>
              <span className="mt-1 block text-xs text-slate-500">Choose more bins when the distribution needs finer detail.</span>
            </label>
            <button type="button" className="atlas-secondary-button w-full justify-center" onClick={() => setHistogramReload((value) => value + 1)} disabled={histogramState.loading}>
              <RefreshCw size={15} className={histogramState.loading ? "animate-spin" : ""} /> {histogramState.loading ? "Aggregating full data" : "Refresh histogram"}
            </button>
          </div>
          {!selected ? (
            <AtlasAttentionPanel title="No predictors available" tone="info">The backend profile did not return any eligible predictors for visualization.</AtlasAttentionPanel>
          ) : selectedIsNumeric ? (
            <div className="grid gap-4 xl:grid-cols-2">
              <div className="xl:col-span-2">
                <HistogramChart
                  bins={resolvedHistogram}
                  source={selected}
                  scope="Full Dataset Aggregation"
                  requestedBins={histogramBins}
                  loading={histogramPending}
                  error={dedicatedHistogramCurrent ? histogramState.error : undefined}
                  rowCount={dedicatedHistogramCurrent ? histogramState.rowCount : undefined}
                  onRetry={() => setHistogramReload((value) => value + 1)}
                />
              </div>
              <QuantileSummary row={selected} />
              <EventRateByQuantile rows={safeArray<any>(selected.event_rate_by_quantile)} />
              <MissingPresentRates row={selected} />
            </div>
          ) : (
            <div className="grid gap-4 xl:grid-cols-2">
              <CategoryFrequencyChart rows={safeArray<any>(selected.top_levels)} scope="Full Dataset Aggregation" />
              <CategoryEventRateChart rows={safeArray<any>(selected.top_levels)} />
              <MetricGrid items={[["Rare levels", formatNumber(selected.rare_level_count, 0)], ["Cardinality", formatNumber(selected.cardinality, 0)], ["Missing", formatPercent(selected.missing_rate)], ["Suggested grouping", selected.suggested_grouping ?? "Not evaluated"]]} />
            </div>
          )}
        </div>
      </AtlasWorkflowSection>
      <AtlasWorkflowSection
        eyebrow="Advanced analysis"
        title="Interactive Distribution Explorer (Visual Intelligence)"
        description="Server-side histogram, quantile, and segment aggregation for enterprise-scale datasets -- brush a range or enter numeric cutoffs to see bounded aggregate statistics without loading full columns into the browser."
        tone="neutral"
      >
        {/* EDA-EXPLORER-001 / Part E: development EDA is explicitly a
            development-context analysis. TRAIN/TEST/OOT partitions and durable
            Scoring Runs do not exist yet, so those controls are suppressed. */}
        <VisualAnalysisPanel
          analysisType="distribution"
          analysisContext="development"
          title="Interactive Distribution Explorer"
          description="Explore how a predictor is distributed across the governed development dataset, and how a selected value range relates to the target."
        >
          <DistributionExplorer />
        </VisualAnalysisPanel>
      </AtlasWorkflowSection>
      <DataTable
        title="All numeric predictors"
        inventoryCount={{ shown: numeric.length, matched: numericMatches.length, total: allNumeric.length }}
        searchTerm={searchActive ? search : ""}
        onClearSearch={() => setSearch("")}
        highlightFeature={selectedName}
        columns={[
          ["feature", "Feature"], ["count", "Count"], ["missing_rate", "Missing", "percent"], ["mean", "Mean"],
          ["standard_deviation", "Std. dev."], ["median", "Median"], ["skewness", "Skew"], ["outlier_rate", "Outliers", "percent"],
          [data.problem_type === "classification" ? "iv" : "correlation_with_target", data.problem_type === "classification" ? "IV" : "Correlation"], ["monotonicity", "Monotonicity"],
        ]}
        rows={numeric}
        empty="No numeric predictors match the current search."
      />
      <DataTable
        title="All categorical predictors"
        inventoryCount={{ shown: categorical.length, matched: categoricalMatches.length, total: allCategorical.length }}
        searchTerm={searchActive ? search : ""}
        onClearSearch={() => setSearch("")}
        highlightFeature={selectedName}
        columns={[
          ["feature", "Feature"], ["count", "Count"], ["missing_rate", "Missing", "percent"], ["cardinality", "Cardinality"],
          ["rare_level_count", "Rare levels"], ["iv", "IV"], ["high_cardinality", "High cardinality", "boolean"], ["inconsistent_labels", "Label cleanup", "boolean"],
        ]}
        rows={categorical}
        empty="No categorical predictors match the current search."
      />
      <DataTable
        title="Missingness diagnostics"
        columns={[["feature", "Feature"], ["missing_count", "Missing rows"], ["missing_rate", "Missing", "percent"], ["missing_event_rate", "Event rate when missing", "percent"], ["present_event_rate", "Event rate when present", "percent"], ["informative_missingness", "Informative flag", "boolean"]]}
        rows={missing}
        empty="No missing predictor values were detected."
      />
    </div>
  );
}

function RelationshipsPanel(props: {
  data: WorkspaceResponse;
  numericFields: string[];
  pairwiseFeatures: string[];
  onPairwiseFeatures: (values: string[]) => void;
  onRun: () => void;
}) {
  const columns = safeArray<string>(props.data.correlation_columns);
  const matrix = safeArray<Array<number | null>>(props.data.correlation_matrix);
  return (
    <div className="space-y-4">
      <AtlasWorkflowSection eyebrow="Association" title="Correlation and Redundancy" description="Correlation and VIF use governed backend data. Pairwise rendering is limited to six explicitly selected variables." tone="info">
        <CorrelationGrid columns={columns} matrix={matrix} />
      </AtlasWorkflowSection>
      <DataTable title="Strong correlated pairs" columns={[["feature_a", "Feature A"], ["feature_b", "Feature B"], ["correlation", "Correlation"]]} rows={props.data.strong_pairs ?? []} empty="No pairs exceed the 0.70 review threshold." />
      <div className="grid gap-4 xl:grid-cols-[1.15fr_0.85fr]">
        <VifBarChart rows={props.data.vif ?? []} />
        <DataTable title="Variance inflation factor" columns={[["feature", "Feature"], ["vif", "VIF"], ["status", "Status"]]} rows={props.data.vif ?? []} empty="VIF requires at least two eligible numeric predictors." />
      </div>
      <DataTable title="Target association ranking" columns={[["feature", "Feature"], [props.data.problem_type === "classification" ? "iv" : "correlation_with_target", props.data.problem_type === "classification" ? "IV" : "Correlation"], ["monotonicity", "Monotonicity"]]} rows={safeArray<any>(props.data.numeric)} empty="No target association ranking is available." />
      <AtlasWorkflowSection
        eyebrow="Bounded chart data"
        title="Pairwise Plot Builder"
        description={safeArray<string>(props.data.pairwise_features).length ? `Selected variables: ${safeArray<string>(props.data.pairwise_features).join(", ")}. The returned ${formatNumber(props.data.pairwise_rows, 0)} rows are for visualization only.` : "Select the predictors beside the plot area, then generate the bounded pairwise view."}
        tone="neutral"
        action={safeArray<string>(props.data.pairwise_features).length ? <AtlasDataScopeBadge scope="rendered_sample" rows={props.data.pairwise_rows} /> : undefined}
      >
        <div className="grid gap-4 xl:grid-cols-[320px_1fr]">
          <div className="rounded-lg border border-slate-200 bg-slate-50 p-3">
            <div className="text-sm font-semibold text-slate-950">Pairwise feature selection</div>
            <div className="mt-1 text-xs text-slate-600">Choose up to four predictors by default. The hard cap is six.</div>
            <div className="mt-3 max-h-72 space-y-1 overflow-auto">
              {safeArray<string>(props.numericFields).map((feature) => {
                const checked = props.pairwiseFeatures.includes(feature);
                const disabled = !checked && props.pairwiseFeatures.length >= 6;
                return (
                  <label key={feature} className="flex items-center gap-2 rounded px-2 py-1.5 text-xs hover:bg-white">
                    <input
                      type="checkbox"
                      checked={checked}
                      disabled={disabled}
                      onChange={() => props.onPairwiseFeatures(checked ? props.pairwiseFeatures.filter((value) => value !== feature) : [...props.pairwiseFeatures, feature])}
                    />
                    <span className="truncate">{feature}</span>
                  </label>
                );
              })}
            </div>
            <button type="button" className="atlas-primary-button mt-3 w-full" onClick={props.onRun}>Generate pairwise plot</button>
          </div>
          <div className="space-y-3">
            {safeArray<string>(props.data.pairwise_features).length ? (
              <>
                {Number(props.data.pairwise_event_rows ?? 0) < 5 && props.data.problem_type === "classification" ? <AtlasAttentionPanel title="Small event count in render sample" tone="warning">The pairwise render sample contains fewer than five event rows. Use the full-dataset association metrics for final decisions.</AtlasAttentionPanel> : null}
                <PairwiseMatrix features={safeArray<string>(props.data.pairwise_features)} rows={safeArray<any>(props.data.pairwise_sample)} />
              </>
            ) : (
              <AtlasAttentionPanel title="Pairwise plot data has not been generated" tone="info">Select up to four predictors and click Generate pairwise plot.</AtlasAttentionPanel>
            )}
          </div>
        </div>
      </AtlasWorkflowSection>
    </div>
  );
}

function StabilityPanel(props: {
  data: WorkspaceResponse;
  dateFields: string[];
  segmentFields: string[];
  dateField: string;
  segmentField: string;
  onDateField: (value: string) => void;
  onSegmentField: (value: string) => void;
  onRun: () => void;
}) {
  const hasTimeFields = safeArray<string>(props.dateFields).length > 0;
  const hasSegmentFields = safeArray<string>(props.segmentFields).length > 0;
  const hasTimeProfile = safeArray(props.data.time_profile).length > 0;
  const hasSegmentProfile = safeArray(props.data.segment_profile).length > 0;
  return (
    <div className="space-y-4">
      <AtlasWorkflowSection eyebrow="Population stability" title="Time and Segment Configuration" description="ATLAS only runs these analyses after a reviewer selects a legitimate time or business segment field." tone="info">
        <AnalysisSelectors {...props} />
        <div className="mt-4">
          <MetricGrid
            items={[
              ["Available time fields", formatNumber(props.dateFields.length, 0)],
              ["Available segment fields", formatNumber(props.segmentFields.length, 0)],
              ["Selected time field", props.dateField || "None selected"],
              ["Selected segment field", props.segmentField || "None selected"],
            ]}
          />
        </div>
      </AtlasWorkflowSection>
      {!hasTimeFields && !hasSegmentFields ? (
        <AtlasAttentionPanel title="No governed time or segment fields were detected" tone="info">
          This dataset does not expose an obvious date, period, or reusable business segment field. ATLAS will not invent segments from arbitrary numeric predictors. Define a governed segment or time field upstream if stability analysis is required.
        </AtlasAttentionPanel>
      ) : !hasTimeProfile && !hasSegmentProfile ? (
        <AtlasAttentionPanel title="No governed time or segment field has been selected" tone="info">Choose a valid time or segment field, then run the analysis. ATLAS will not infer a date from ordinary numeric values.</AtlasAttentionPanel>
      ) : null}
      <div className="grid gap-4 xl:grid-cols-2">
        <CompactGroupTable title="Volume and event rate by time" rows={safeArray(props.data.time_profile)} />
        <CompactGroupTable title="Population and event rate by segment" rows={safeArray(props.data.segment_profile)} />
      </div>
      {props.data.out_of_time_suggestion ? (
        <AtlasWorkflowSection eyebrow="Validation option" title="Potential Out-of-Time Window" tone="warning">
          <p className="text-sm text-slate-700">{props.data.out_of_time_suggestion.rationale}</p>
          <div className="mt-2 text-xs text-slate-600">Comparison periods: {safeArray<string>(props.data.out_of_time_suggestion.comparison_periods).join(", ")}</div>
        </AtlasWorkflowSection>
      ) : null}
    </div>
  );
}

function FindingsPanel({ data, state, onChange, onSave, message }: { data: WorkspaceResponse; state: FindingsState; onChange: (value: FindingsState) => void; onSave: () => void; message: string }) {
  const [duplicateTreatment, setDuplicateTreatment] = useState("review");
  const [duplicateMessage, setDuplicateMessage] = useState("");
  const duplicateFinding = safeArray<any>(data.findings).find((finding: any) => String(finding.category).toLowerCase() === "data integrity" && /duplicate/i.test(String(finding.finding)));
  function saveDuplicateDecision() {
    logDecision({
      workflowStep: "Exploratory Data Analysis",
      actionType: "workflow_setting_changed",
      subject: "Duplicate row treatment",
      previousValue: "review",
      newValue: duplicateTreatment,
      systemRecommendation: "Confirm whether duplicate records represent repeated observations or ingestion duplication before downstream modeling.",
      userReason: duplicateTreatment === "exclude" ? "Reviewer selected duplicate-row exclusion for downstream preprocessing." : "Reviewer recorded duplicate-row handling decision.",
    });
    setDuplicateMessage("Duplicate-row decision recorded.");
  }
  return (
    <div className="space-y-4">
      <AtlasWorkflowSection eyebrow="Governed conclusions" title="EDA Findings and Carry-Forward" description="Recommendations inform later choices but do not automatically apply outlier, missing-value, feature, or split treatments." tone="info">
        <div className="space-y-2">
          {safeArray<any>(data.findings).map((finding: any, index: number) => (
            <div key={`${finding.category}-${index}`} className={`rounded-lg border p-3 ${finding.severity === "warning" ? "border-amber-300 bg-amber-50" : "border-blue-200 bg-blue-50"}`}>
              <div className="flex items-start gap-2">
                {finding.severity === "warning" ? <AlertTriangle size={17} className="mt-0.5 shrink-0 text-amber-700" /> : <CheckCircle2 size={17} className="mt-0.5 shrink-0 text-blue-700" />}
                <div>
                  <div className="text-sm font-semibold text-slate-950">{finding.category}</div>
                  <div className="mt-1 text-sm text-slate-700">{finding.finding}</div>
                  <div className="mt-1 text-xs text-slate-600"><strong>Recommended action:</strong> {finding.recommended_action}</div>
                </div>
              </div>
            </div>
          ))}
        </div>
      </AtlasWorkflowSection>
      {duplicateFinding ? (
        <AtlasWorkflowSection eyebrow="Duplicate row treatment" title="Duplicate Row Decision" description="Record how duplicate observations should be handled before the dataset moves into treatment and model training." tone="warning">
          <div className="grid gap-4 lg:grid-cols-[1fr_auto] lg:items-end">
            <label>
              <span className="atlas-label">Duplicate row action</span>
              <select className="atlas-input mt-1" value={duplicateTreatment} onChange={(event) => setDuplicateTreatment(event.target.value)}>
                <option value="review">Review before downstream treatment</option>
                <option value="exclude">Exclude duplicate rows before downstream modeling</option>
                <option value="keep">Keep duplicate rows as repeated observations</option>
              </select>
              <span className="mt-1 block text-xs text-slate-600">
                This records the EDA decision. Dataset mutation should occur through governed preprocessing evidence before training.
              </span>
            </label>
            <button type="button" className="atlas-primary-button" onClick={saveDuplicateDecision}>Save duplicate-row decision</button>
          </div>
          {duplicateMessage ? <div className="mt-3 text-sm font-medium text-emerald-700">{duplicateMessage}</div> : null}
        </AtlasWorkflowSection>
      ) : null}
      <AtlasWorkflowSection eyebrow="Reviewer record" title="Conclusion and Status" tone="neutral">
        <div className="grid gap-4 lg:grid-cols-[1fr_220px]">
          <label className="block">
            <span className="atlas-label">Reviewer commentary</span>
            <textarea className="atlas-input mt-1 min-h-32" value={state.commentary} onChange={(event) => onChange({ ...state, commentary: event.target.value })} placeholder="Record key conclusions, exceptions, and downstream review priorities." />
          </label>
          <label className="block">
            <span className="atlas-label">Finding status</span>
            <select className="atlas-input mt-1" value={state.status} onChange={(event) => onChange({ ...state, status: event.target.value as FindingsState["status"] })}>
              <option value="draft">Draft</option>
              <option value="reviewed">Reviewed</option>
              <option value="accepted">Accepted for carry-forward</option>
            </select>
          </label>
        </div>
        <div className="mt-4 flex flex-wrap items-center gap-2">
          <button type="button" className="atlas-primary-button" onClick={onSave}><Save size={15} /> Save to Evidence Center</button>
          {message ? <span className="text-sm text-slate-600">{message}</span> : null}
        </div>
      </AtlasWorkflowSection>
    </div>
  );
}

function AnalysisSelectors(props: any) {
  return (
    <div className="grid gap-3 lg:grid-cols-[1fr_1fr_auto] lg:items-end">
      <label>
        <span className="atlas-label">Time field</span>
        <select className="atlas-input mt-1" value={props.dateField} onChange={(event) => props.onDateField(event.target.value)}>
          <option value="">No time analysis</option>
          {safeArray<string>(props.dateFields).map((field: string) => <option key={field} value={field}>{field}</option>)}
        </select>
      </label>
      <label>
        <span className="atlas-label">Segment field</span>
        <select className="atlas-input mt-1" value={props.segmentField} onChange={(event) => props.onSegmentField(event.target.value)}>
          <option value="">No segment analysis</option>
          {safeArray<string>(props.segmentFields).map((field: string) => <option key={field} value={field}>{field}</option>)}
        </select>
      </label>
      <button type="button" className="atlas-primary-button" onClick={props.onRun}>Run analysis</button>
    </div>
  );
}

function MetricGrid({ items }: { items: Array<[string, React.ReactNode]> }) {
  return <div className="grid gap-2 sm:grid-cols-2 xl:grid-cols-3">{items.map(([label, value]) => <div key={label} className="rounded-lg border border-slate-200 bg-white px-3 py-2.5"><div className="text-[11px] font-semibold uppercase text-slate-500">{label}</div><div className="mt-1 text-base font-semibold text-slate-950">{value}</div></div>)}</div>;
}

function StatusList({ items }: { items: Array<{ label: string; value: string; warning: boolean }> }) {
  return <div className="space-y-2">{items.map((item) => <div key={item.label} className="flex items-center justify-between gap-3 border-b border-slate-200 pb-2 text-sm last:border-0 last:pb-0"><span className="text-slate-600">{item.label}</span><span className={item.warning ? "font-semibold text-amber-800" : "font-semibold text-emerald-700"}>{item.value}</span></div>)}</div>;
}

function HorizontalBars({ rows }: { rows: Array<{ label: string; value: number; detail: string }> }) {
  const safeRows = safeArray<{ label: string; value: number; detail: string }>(rows);
  const max = Math.max(1, ...safeRows.map((row) => row.value));
  return <div className="mt-4 space-y-2">{safeRows.map((row) => <div key={row.label} className="grid grid-cols-[minmax(80px,180px)_1fr_auto] items-center gap-3 text-xs"><span className="truncate font-medium text-slate-700">{row.label}</span><span className="h-2 overflow-hidden rounded bg-slate-200"><span className="block h-full rounded bg-blue-600" style={{ width: `${Math.max(2, (row.value / max) * 100)}%` }} /></span><span className="w-24 text-right tabular-nums text-slate-600">{formatNumber(row.value, 0)} | {row.detail}</span></div>)}</div>;
}

function ChartCard({ title, scope, children }: { title: string; scope?: string; children: React.ReactNode }) {
  return (
    <div className="rounded-lg border border-slate-200 bg-white p-3">
      <div className="flex items-center justify-between gap-3">
        <div className="text-sm font-semibold text-slate-950">{title}</div>
        {scope ? <span className="rounded-full border border-blue-200 bg-blue-50 px-2 py-1 text-[10px] font-semibold uppercase tracking-wide text-blue-700">{scope}</span> : null}
      </div>
      <div className="mt-3">{children}</div>
    </div>
  );
}

function ClassDistributionChart({ rows, scope }: { rows: any[]; scope?: string }) {
  const safeRows = safeArray<any>(rows);
  const max = Math.max(1, ...safeRows.map((row) => Number(row.count ?? row.value ?? 0)));
  if (!safeRows.length) return <ChartCard title="Class Distribution" scope={scope}><div className="text-sm text-slate-500">Target class distribution is not available.</div></ChartCard>;
  return (
    <ChartCard title="Class Distribution" scope={scope}>
      <div className="space-y-2">
        {safeRows.map((row, index) => {
          const label = String(row.class ?? row.label ?? row.value ?? `Class ${index + 1}`);
          const count = Number(row.count ?? 0);
          const rate = Number(row.rate ?? row.percent ?? row.share);
          return (
            <div key={`${label}-${index}`} className="grid grid-cols-[minmax(90px,150px)_1fr_auto] items-center gap-3 text-xs">
              <span className="truncate font-medium text-slate-700">{label}</span>
              <span className="h-3 overflow-hidden rounded-full bg-slate-100">
                <span className="block h-full rounded-full bg-emerald-500" style={{ width: `${Math.max(2, (count / max) * 100)}%` }} />
              </span>
              <span className="w-32 text-right tabular-nums text-slate-600">{formatNumber(count, 0)} | {formatPercent(rate)}</span>
            </div>
          );
        })}
      </div>
    </ChartCard>
  );
}

function chartBins(source: any) {
  const explicit = safeArray<any>(source?.histogram).length
    ? safeArray<any>(source?.histogram)
    : safeArray<any>(source?.histogram_bins).length
      ? safeArray<any>(source?.histogram_bins)
      : safeArray<any>(source?.bins).length
        ? safeArray<any>(source?.bins)
        : safeArray<any>(source?.distribution_bins);
  return explicit;
}

function HistogramChart({
  bins,
  source,
  scope,
  requestedBins,
  loading = false,
  error,
  rowCount,
  onRetry,
}: {
  bins: any[];
  source?: any;
  scope?: string;
  requestedBins?: number;
  loading?: boolean;
  error?: string;
  rowCount?: number;
  onRetry?: () => void;
}) {
  const safeBins = safeArray<any>(bins);
  const max = Math.max(1, ...safeBins.map((bin) => Number(bin.count ?? 0)));
  if (!safeBins.length && loading) {
    return (
      <ChartCard title="Distribution Explorer" scope={scope}>
        <div className="flex h-96 flex-col justify-end gap-3 overflow-hidden rounded-lg border border-blue-100 bg-white p-6" aria-label="Loading histogram">
          <div className="mb-auto flex items-center gap-2 text-sm font-semibold text-blue-800"><LoaderCircle size={16} className="animate-spin" /> Aggregating {requestedBins ?? 20} bins across the full registered dataset</div>
          <div className="flex h-64 items-end gap-2 border-b border-l border-slate-200 px-4">
            {[36, 52, 78, 96, 84, 62, 44, 28, 18, 10].map((height, index) => <div key={index} className="flex-1 animate-pulse rounded-t bg-blue-100" style={{ height: `${height}%` }} />)}
          </div>
        </div>
      </ChartCard>
    );
  }
  if (!safeBins.length) return (
    <ChartCard title="Distribution Explorer" scope={scope}>
      <div className="flex h-96 flex-col items-center justify-center rounded-lg border border-amber-200 bg-amber-50 px-8 text-center">
        <AlertTriangle size={28} className="text-amber-600" />
        <div className="mt-3 text-sm font-semibold text-amber-950">Histogram data could not be materialized</div>
        <div className="mt-1 max-w-xl text-sm leading-6 text-amber-900">{error || "The backend did not return numeric histogram bins for this predictor."}</div>
        {onRetry ? <button type="button" className="atlas-secondary-button mt-4 bg-white" onClick={onRetry}><RefreshCw size={15} /> Retry full-data aggregation</button> : null}
      </div>
    </ChartCard>
  );
  const min = Number(safeBins[0]?.lower);
  const maxValue = Number(safeBins[safeBins.length - 1]?.upper);
  const mean = Number(source?.mean);
  const median = Number(source?.median);
  const q1 = Number(source?.q1);
  const q3 = Number(source?.q3);
  const width = 960;
  const height = 380;
  const margin = { top: 34, right: 24, bottom: 56, left: 66 };
  const plotWidth = width - margin.left - margin.right;
  const plotHeight = height - margin.top - margin.bottom;
  const slotWidth = plotWidth / safeBins.length;
  const barGap = Math.min(4, Math.max(1, slotWidth * 0.12));
  const barWidth = Math.max(1, slotWidth - barGap);
  const markerPosition = (value: number) => {
    if (!Number.isFinite(value) || !Number.isFinite(min) || !Number.isFinite(maxValue) || min === maxValue) return null;
    return margin.left + Math.max(0, Math.min(1, (value - min) / (maxValue - min))) * plotWidth;
  };
  const meanPosition = markerPosition(mean);
  const medianPosition = markerPosition(median);
  const q1Position = markerPosition(q1);
  const q3Position = markerPosition(q3);
  const yTicks = [0, 0.25, 0.5, 0.75, 1];
  const xTicks = [0, 0.25, 0.5, 0.75, 1];
  const densityPoints = safeBins.map((bin, index) => {
    const x = margin.left + index * slotWidth + slotWidth / 2;
    const y = margin.top + plotHeight - (Number(bin.count ?? 0) / max) * plotHeight;
    return `${x},${y}`;
  }).join(" ");
  const skew = Number(source?.skewness);
  const shape = !Number.isFinite(skew)
    ? "Not evaluated"
    : Math.abs(skew) < 0.35
      ? "Near symmetric"
      : `${Math.abs(skew) >= 1 ? "Strong" : "Moderate"} ${skew > 0 ? "right" : "left"} skew`;
  const observedRows = Number.isFinite(Number(rowCount)) ? Number(rowCount) : Number(source?.count);
  return (
    <ChartCard title="Distribution Explorer" scope={scope}>
      {loading ? <div className="mb-2 flex items-center gap-2 text-xs font-medium text-blue-700"><LoaderCircle size={14} className="animate-spin" /> Recomputing {requestedBins ?? safeBins.length} bins on the full dataset</div> : null}
      <div className="overflow-x-auto rounded-lg border border-slate-200 bg-white">
        <svg className="h-auto min-w-[760px] w-full" viewBox={`0 0 ${width} ${height}`} role="img" aria-label={`Histogram with ${safeBins.length} bins`}>
          <rect x={margin.left} y={margin.top} width={plotWidth} height={plotHeight} fill="#f8fafc" />
          {q1Position !== null && q3Position !== null ? <rect x={Math.min(q1Position, q3Position)} y={margin.top} width={Math.abs(q3Position - q1Position)} height={plotHeight} fill="#dbeafe" opacity="0.52" /> : null}
          {yTicks.map((fraction) => {
            const y = margin.top + plotHeight - fraction * plotHeight;
            return <g key={fraction}><line x1={margin.left} x2={margin.left + plotWidth} y1={y} y2={y} stroke="#dbe3ee" strokeDasharray={fraction ? "3 5" : undefined} /><text x={margin.left - 12} y={y + 4} textAnchor="end" fontSize="11" fill="#64748b">{formatNumber(max * fraction, 0)}</text></g>;
          })}
          {safeBins.map((bin, index) => {
            const count = Number(bin.count ?? 0);
            const barHeight = (count / max) * plotHeight;
            const x = margin.left + index * slotWidth + barGap / 2;
            const y = margin.top + plotHeight - barHeight;
            return <rect key={`${bin.lower}-${bin.upper}-${index}`} x={x} y={y} width={barWidth} height={Math.max(1, barHeight)} rx="2" fill="#2563eb" opacity="0.88"><title>{`${formatNumber(bin.lower, 3)} to ${formatNumber(bin.upper, 3)}: ${formatNumber(count, 0)} rows`}</title></rect>;
          })}
          <polyline points={densityPoints} fill="none" stroke="#0f766e" strokeWidth="2" strokeLinejoin="round" strokeLinecap="round" opacity="0.9" />
          {meanPosition !== null ? <g><line x1={meanPosition} x2={meanPosition} y1={margin.top - 4} y2={margin.top + plotHeight} stroke="#d97706" strokeWidth="2" /><rect x={Math.max(margin.left, Math.min(meanPosition - 46, width - 120))} y="4" width="92" height="22" rx="4" fill="#fffbeb" stroke="#f59e0b" /><text x={Math.max(margin.left + 46, Math.min(meanPosition, width - 74))} y="19" textAnchor="middle" fontSize="11" fontWeight="700" fill="#92400e">Mean {formatNumber(mean, 2)}</text></g> : null}
          {medianPosition !== null ? <g><line x1={medianPosition} x2={medianPosition} y1={margin.top} y2={margin.top + plotHeight} stroke="#059669" strokeWidth="2" /><rect x={Math.max(margin.left, Math.min(medianPosition - 48, width - 124))} y={margin.top + 8} width="96" height="22" rx="4" fill="#ecfdf5" stroke="#10b981" /><text x={Math.max(margin.left + 48, Math.min(medianPosition, width - 76))} y={margin.top + 23} textAnchor="middle" fontSize="11" fontWeight="700" fill="#065f46">Median {formatNumber(median, 2)}</text></g> : null}
          {xTicks.map((fraction) => {
            const x = margin.left + fraction * plotWidth;
            const value = min + fraction * (maxValue - min);
            return <g key={fraction}><line x1={x} x2={x} y1={margin.top + plotHeight} y2={margin.top + plotHeight + 6} stroke="#94a3b8" /><text x={x} y={margin.top + plotHeight + 24} textAnchor="middle" fontSize="11" fill="#64748b">{formatNumber(value, Math.abs(maxValue - min) < 10 ? 3 : 1)}</text></g>;
          })}
          <text x={margin.left + plotWidth / 2} y={height - 8} textAnchor="middle" fontSize="12" fontWeight="600" fill="#475569">Feature value</text>
          <text x="16" y={margin.top + plotHeight / 2} textAnchor="middle" fontSize="12" fontWeight="600" fill="#475569" transform={`rotate(-90 16 ${margin.top + plotHeight / 2})`}>Record count</text>
        </svg>
      </div>
      <div className="mt-3 grid gap-2 sm:grid-cols-3 xl:grid-cols-6">
        <div className="rounded border border-slate-200 bg-slate-50 px-3 py-2"><div className="text-[10px] font-semibold uppercase text-slate-500">Observed rows</div><div className="text-sm font-semibold text-slate-950">{formatNumber(observedRows, 0)}</div></div>
        <div className="rounded border border-slate-200 bg-slate-50 px-3 py-2"><div className="text-[10px] font-semibold uppercase text-slate-500">Bins</div><div className="text-sm font-semibold text-slate-950">{safeBins.length}</div></div>
        <div className="rounded border border-slate-200 bg-slate-50 px-3 py-2"><div className="text-[10px] font-semibold uppercase text-slate-500">Peak count</div><div className="text-sm font-semibold text-slate-950">{formatNumber(max, 0)}</div></div>
        <div className="rounded border border-blue-200 bg-blue-50 px-3 py-2"><div className="text-[10px] font-semibold uppercase text-blue-700">Distribution shape</div><div className="text-sm font-semibold text-slate-950">{shape}</div></div>
        <div className="rounded border border-amber-200 bg-amber-50 px-3 py-2"><div className="text-[10px] font-semibold uppercase text-amber-700">Mean</div><div className="text-sm font-semibold text-slate-950">{formatNumber(mean, 3)}</div></div>
        <div className="rounded border border-emerald-200 bg-emerald-50 px-3 py-2"><div className="text-[10px] font-semibold uppercase text-emerald-700">Median</div><div className="text-sm font-semibold text-slate-950">{formatNumber(median, 3)}</div></div>
      </div>
      <div className="mt-3 flex flex-wrap gap-2 text-xs">
        <span className="rounded-full border border-blue-200 bg-blue-50 px-2.5 py-1 font-semibold text-blue-800">IQR {formatNumber(q1, 3)} to {formatNumber(q3, 3)}</span>
        <span className="rounded-full border border-slate-200 bg-slate-50 px-2.5 py-1 font-semibold text-slate-700">Missing {formatPercent(source?.missing_rate)}</span>
        <span className="rounded-full border border-red-200 bg-red-50 px-2.5 py-1 font-semibold text-red-800">Outliers {formatPercent(source?.outlier_rate)}</span>
        {source?.iv !== null && source?.iv !== undefined ? <span className="rounded-full border border-emerald-200 bg-emerald-50 px-2.5 py-1 font-semibold text-emerald-800">Information value {formatNumber(source.iv, 4)}</span> : null}
        {source?.monotonicity ? <span className="rounded-full border border-violet-200 bg-violet-50 px-2.5 py-1 font-semibold text-violet-800">{source.monotonicity}</span> : null}
      </div>
      {error ? <div className="mt-2 flex items-center gap-2 text-xs font-medium text-amber-700"><AlertTriangle size={13} /> Live histogram refresh failed; the matching profile aggregation is shown. {error}</div> : null}
      {requestedBins && safeBins.length !== requestedBins ? <div className="mt-2 text-xs font-medium text-amber-700">Requested {requestedBins} bins; the backend returned {safeBins.length}. Refresh the dataset profile if this persists.</div> : null}
    </ChartCard>
  );
}

function QuantileSummary({ row }: { row: any }) {
  return (
    <ChartCard title="Quantile Summary" scope="Full Dataset Aggregation">
      <MetricGrid items={[
        ["Minimum", formatNumber(row.min ?? row.minimum)],
        ["Q1", formatNumber(row.q1)],
        ["Median", formatNumber(row.median)],
        ["Q3", formatNumber(row.q3)],
        ["Maximum", formatNumber(row.max ?? row.maximum)],
        ["Missing", formatPercent(row.missing_rate)],
      ]} />
    </ChartCard>
  );
}

function EventRateByQuantile({ rows }: { rows: any[] }) {
  const safeRows = safeArray<any>(rows);
  const max = Math.max(0.01, ...safeRows.map((row) => Number(row.event_rate ?? 0)));
  if (!safeRows.length) return <ChartCard title="Event Rate by Quantile" scope="Full Dataset Aggregation"><div className="text-sm text-slate-500">Event-rate by quantile is not available for this feature.</div></ChartCard>;
  return (
    <ChartCard title="Event Rate by Quantile" scope="Full Dataset Aggregation">
      <div className="space-y-2">
        {safeRows.map((row, index) => {
          const rate = Number(row.event_rate ?? 0);
          const label = String(row.bucket ?? row.quantile ?? `Q${index + 1}`);
          return (
            <div key={`${label}-${index}`} className="grid grid-cols-[74px_1fr_80px] items-center gap-3 text-xs">
              <span className="truncate font-medium text-slate-700">{label}</span>
              <span className="h-2 overflow-hidden rounded bg-slate-200"><span className="block h-full rounded bg-emerald-500" style={{ width: `${Math.max(2, (rate / max) * 100)}%` }} /></span>
              <span className="text-right tabular-nums text-slate-600">{formatPercent(rate)}</span>
            </div>
          );
        })}
      </div>
    </ChartCard>
  );
}

function MissingPresentRates({ row }: { row: any }) {
  return (
    <ChartCard title="Missing and Present Target Rates" scope="Full Dataset Aggregation">
      <MetricGrid items={[
        ["Present event rate", formatPercent(row.present_event_rate)],
        ["Missing event rate", formatPercent(row.missing_event_rate)],
        ["Present rows", formatNumber(row.present_count, 0)],
        ["Missing rows", formatNumber(row.missing_count, 0)],
      ]} />
    </ChartCard>
  );
}

function CategoryFrequencyChart({ rows, scope }: { rows: any[]; scope?: string }) {
  const safeRows = safeArray<any>(rows);
  const max = Math.max(1, ...safeRows.map((row) => Number(row.count ?? 0)));
  if (!safeRows.length) return <ChartCard title="Category Frequency" scope={scope}><div className="text-sm text-slate-500">Category frequency data is not available.</div></ChartCard>;
  return (
    <ChartCard title="Category Frequency" scope={scope}>
      <div className="space-y-2">
        {safeRows.slice(0, 12).map((row, index) => {
          const label = String(row.level ?? row.category ?? row.value ?? `Level ${index + 1}`);
          const count = Number(row.count ?? 0);
          return <div key={`${label}-${index}`} className="grid grid-cols-[minmax(100px,180px)_1fr_70px] items-center gap-3 text-xs"><span className="truncate font-medium text-slate-700">{label}</span><span className="h-2 overflow-hidden rounded bg-slate-200"><span className="block h-full rounded bg-blue-500" style={{ width: `${Math.max(2, (count / max) * 100)}%` }} /></span><span className="text-right tabular-nums text-slate-600">{formatNumber(count, 0)}</span></div>;
        })}
      </div>
    </ChartCard>
  );
}

function CategoryEventRateChart({ rows }: { rows: any[] }) {
  const safeRows = safeArray<any>(rows);
  const max = Math.max(0.01, ...safeRows.map((row) => Number(row.event_rate ?? 0)));
  if (!safeRows.length) return <ChartCard title="Category Event Rate" scope="Full Dataset Aggregation"><div className="text-sm text-slate-500">Category event-rate data is not available.</div></ChartCard>;
  return (
    <ChartCard title="Category Event Rate" scope="Full Dataset Aggregation">
      <div className="space-y-2">
        {safeRows.slice(0, 12).map((row, index) => {
          const label = String(row.level ?? row.category ?? row.value ?? `Level ${index + 1}`);
          const rate = Number(row.event_rate ?? 0);
          return <div key={`${label}-${index}`} className="grid grid-cols-[minmax(100px,180px)_1fr_80px] items-center gap-3 text-xs"><span className="truncate font-medium text-slate-700">{label}</span><span className="h-2 overflow-hidden rounded bg-slate-200"><span className="block h-full rounded bg-emerald-500" style={{ width: `${Math.max(2, (rate / max) * 100)}%` }} /></span><span className="text-right tabular-nums text-slate-600">{formatPercent(rate)}</span></div>;
        })}
      </div>
    </ChartCard>
  );
}

function PairwiseMatrix({ features, rows }: { features: string[]; rows: any[] }) {
  const safeFeatures = safeArray<string>(features).slice(0, 6);
  const safeRows = safeArray<any>(rows).slice(0, 600);
  if (safeFeatures.length < 2 || !safeRows.length) return <div className="rounded-lg border border-slate-200 bg-white p-4 text-sm text-slate-500">Pairwise plot data is not available for the selected features.</div>;
  return (
    <div className="overflow-auto rounded-lg border border-slate-200 bg-white p-3">
      <div className="grid min-w-[720px] gap-1" style={{ gridTemplateColumns: `120px repeat(${safeFeatures.length}, minmax(120px, 1fr))` }}>
        <div />
        {safeFeatures.map((feature) => <div key={`head-${feature}`} className="truncate px-2 py-1 text-center text-[10px] font-semibold uppercase text-slate-500" title={feature}>{feature}</div>)}
        {safeFeatures.flatMap((yFeature) => [
          <div key={`row-${yFeature}`} className="truncate px-2 py-10 text-[10px] font-semibold uppercase text-slate-500" title={yFeature}>{yFeature}</div>,
          ...safeFeatures.map((xFeature) => (
            <div key={`${yFeature}-${xFeature}`} className="h-32 rounded border border-slate-100 bg-slate-50">
              {xFeature === yFeature ? <MiniHistogramValues rows={safeRows} feature={xFeature} /> : <ScatterCell rows={safeRows} xFeature={xFeature} yFeature={yFeature} />}
            </div>
          )),
        ])}
      </div>
    </div>
  );
}

function MiniHistogramValues({ rows, feature }: { rows: any[]; feature: string }) {
  const values = safeArray<any>(rows).map((row) => Number(row[feature])).filter(Number.isFinite);
  if (!values.length) return <div className="flex h-full items-center justify-center text-[10px] text-slate-400">No numeric data</div>;
  const min = Math.min(...values);
  const max = Math.max(...values);
  const bins = Array.from({ length: 10 }, () => 0);
  values.forEach((value) => {
    const index = min === max ? 0 : Math.min(9, Math.floor(((value - min) / (max - min)) * 10));
    bins[index] += 1;
  });
  const maxBin = Math.max(1, ...bins);
  return <div className="flex h-full items-end gap-0.5 p-2">{bins.map((count, index) => <span key={index} className="block flex-1 rounded-t bg-blue-400" style={{ height: `${Math.max(4, (count / maxBin) * 100)}%` }} />)}</div>;
}

function ScatterCell({ rows, xFeature, yFeature }: { rows: any[]; xFeature: string; yFeature: string }) {
  const points = safeArray<any>(rows).map((row) => ({ x: Number(row[xFeature]), y: Number(row[yFeature]), event: !!row.__event__ })).filter((point) => Number.isFinite(point.x) && Number.isFinite(point.y));
  if (!points.length) return <div className="flex h-full items-center justify-center text-[10px] text-slate-400">No numeric data</div>;
  const xMin = Math.min(...points.map((point) => point.x));
  const xMax = Math.max(...points.map((point) => point.x));
  const yMin = Math.min(...points.map((point) => point.y));
  const yMax = Math.max(...points.map((point) => point.y));
  const scale = (value: number, min: number, max: number) => (min === max ? 50 : ((value - min) / (max - min)) * 92 + 4);
  return (
    <div className="relative h-full w-full overflow-hidden">
      {points.map((point, index) => (
        <span
          key={index}
          className={`absolute h-1.5 w-1.5 rounded-full ${point.event ? "bg-emerald-600" : "bg-blue-500"} opacity-60`}
          style={{ left: `${scale(point.x, xMin, xMax)}%`, bottom: `${scale(point.y, yMin, yMax)}%` }}
        />
      ))}
    </div>
  );
}

function CompactGroupTable({ title, rows, empty }: { title: string; rows: any[]; empty?: string }) {
  const safeRows = safeArray<any>(rows);
  const maxCount = Math.max(1, ...safeRows.map((row) => Number(row.count ?? 0)).filter(Number.isFinite));
  return (
    <div className="overflow-hidden rounded-xl border border-slate-200 bg-white shadow-sm">
      <div className="border-b border-slate-200 bg-slate-50 px-4 py-3">
        <div className="text-sm font-semibold text-slate-950">{title}</div>
        <div className="mt-1 text-xs text-slate-500">Governed volume, event counts, and event-rate movement for the selected field.</div>
      </div>
      {!safeRows.length ? <div className="p-4 text-sm text-slate-500">{empty || "No governed field is selected or the selected field is not valid for this analysis."}</div> : (
        <div className="max-h-96 overflow-auto p-4">
          <div className="space-y-2.5">
            {safeRows.map((row, index) => {
              const count = Number(row.count ?? 0);
              const events = Number(row.events ?? 0);
              const eventRate = Number(row.event_rate ?? 0);
              return (
                <div key={`${row.group}-${index}`} className="rounded-lg border border-slate-200 bg-white px-3 py-2.5">
                  <div className="flex items-start justify-between gap-3">
                    <div className="min-w-0">
                      <div className="truncate text-sm font-semibold text-slate-950" title={String(row.group)}>{row.group}</div>
                      <div className="mt-1 text-xs text-slate-500">{formatNumber(count, 0)} records | {formatNumber(events, 0)} events</div>
                    </div>
                    <div className="rounded-full border border-emerald-200 bg-emerald-50 px-2.5 py-1 text-xs font-semibold tabular-nums text-emerald-800">{formatPercent(eventRate)}</div>
                  </div>
                  <div className="mt-2 h-2 overflow-hidden rounded-full bg-slate-100">
                    <div className="h-full rounded-full bg-blue-600" style={{ width: `${Math.max(2, Math.min(100, (count / maxCount) * 100))}%` }} />
                  </div>
                </div>
              );
            })}
          </div>
        </div>
      )}
    </div>
  );
}

const dataTableDescriptions: Record<string, string> = {
  "All numeric predictors": "Every numeric predictor in the governed modeling population. Search narrows this list; the selected predictor is highlighted in place.",
  "All categorical predictors": "Every categorical predictor in the governed modeling population. Search narrows this list; the selected predictor is highlighted in place.",
  "Missingness diagnostics": "Missing-volume and target-rate differences used to identify informative missingness.",
  "Strong correlated pairs": "Predictor pairs above the governed correlation review threshold.",
  "Variance inflation factor": "Multicollinearity risk among eligible numeric predictors.",
  "Target association ranking": "Univariate target signal ranked for screening, not automatic selection.",
};

function tableValue(row: any, key: string, type?: string) {
  const value = row?.[key];
  if (type === "percent") return formatPercent(value);
  if (type === "boolean") return value ? "Yes" : "No";
  if (typeof value === "number") {
    if (/count|rows|cardinality|rare_level/i.test(key)) return value.toLocaleString();
    return formatNumber(value, 4);
  }
  return String(value ?? "Not available");
}

function statusClasses(value: string) {
  const normalized = value.toLowerCase();
  if (/yes|high|risk|non-monotonic|fail|severe/.test(normalized)) return "border-amber-200 bg-amber-50 text-amber-900";
  if (/no|low|stable|pass|monotonic|acceptable/.test(normalized)) return "border-emerald-200 bg-emerald-50 text-emerald-800";
  return "border-slate-200 bg-slate-100 text-slate-700";
}

function DataTable({
  title,
  columns,
  rows,
  empty,
  inventoryCount,
  searchTerm = "",
  onClearSearch,
  highlightFeature = "",
}: {
  title: string;
  columns: string[][];
  rows: any[];
  empty: string;
  /** EDA-UX-004: shown/matched/total so a filtered table never looks like the
   *  complete inventory. */
  inventoryCount?: { shown: number; matched: number; total: number };
  searchTerm?: string;
  onClearSearch?: () => void;
  /** The predictor selected in Selected Predictor Visualization, highlighted in
   *  place rather than filtering the inventory down to it. */
  highlightFeature?: string;
}) {
  const safeRows = safeArray<any>(rows);
  const safeColumns = safeArray<string[]>(columns);
  const scaleByKey = Object.fromEntries(safeColumns.map(([key]) => {
    const maximum = Math.max(...safeRows.map((row) => Math.abs(Number(row?.[key]))).filter(Number.isFinite), 0);
    return [key, maximum];
  })) as Record<string, number>;
  const description = dataTableDescriptions[title] ?? "Governed full-data analytical output.";

  return (
    <section className="overflow-hidden rounded-xl border border-slate-200 bg-white shadow-sm">
      <div className="flex flex-col gap-2 border-b border-slate-200 bg-white px-4 py-3 sm:flex-row sm:items-center sm:justify-between">
        <div>
          <div className="flex items-center gap-2">
            <BarChart3 size={15} className="text-blue-700" />
            <h3 className="text-sm font-semibold text-slate-950">{title}</h3>
          </div>
          <p className="mt-1 text-xs leading-5 text-slate-500">{description}</p>
        </div>
        <div className="flex w-fit flex-col items-start gap-1 sm:items-end">
          <span
            className="inline-flex w-fit items-center rounded-full border border-slate-200 bg-slate-50 px-2.5 py-1 text-[11px] font-semibold text-slate-600"
            data-testid="data-table-count"
          >
            {inventoryCount
              ? `Showing ${inventoryCount.shown.toLocaleString()} of ${inventoryCount.matched.toLocaleString()} matching (${inventoryCount.total.toLocaleString()} total)`
              : `${safeRows.length.toLocaleString()} ${safeRows.length === 1 ? "record" : "records"}`}
          </span>
          {searchTerm ? (
            <span
              className="inline-flex w-fit items-center gap-2 rounded-full border border-amber-300 bg-amber-50 px-2.5 py-1 text-[11px] font-semibold text-amber-900"
              data-testid="data-table-filter-notice"
            >
              Filtered by search "{searchTerm}"
              {onClearSearch ? (
                <button type="button" onClick={onClearSearch} className="underline" data-testid="data-table-clear-search">
                  Show all
                </button>
              ) : null}
            </span>
          ) : null}
        </div>
      </div>
      {!safeRows.length ? <div className="flex min-h-28 items-center justify-center px-4 py-6 text-sm text-slate-500">{empty}</div> : (
        <div className="max-h-[460px] overflow-auto">
          <table className="w-full min-w-[980px] border-separate border-spacing-0 text-xs">
            <thead className="sticky top-0 z-20 bg-slate-950 text-white shadow-sm">
              <tr>{safeColumns.map(([, label], columnIndex) => (
                <th
                  key={label}
                  className={`${columnIndex === 0 ? "sticky left-0 z-30 bg-slate-950" : ""} whitespace-nowrap border-b border-slate-800 px-4 py-3 text-left text-[10px] font-semibold uppercase tracking-wide text-slate-200`}
                >
                  {label}
                </th>
              ))}</tr>
            </thead>
            <tbody>
              {safeRows.map((row, rowIndex) => (
                <tr
                  key={`${row.feature ?? row.feature_a ?? row.group ?? rowIndex}-${rowIndex}`}
                  data-selected-predictor={highlightFeature && row.feature === highlightFeature ? "true" : undefined}
                  className={`group even:bg-slate-50/70 hover:bg-blue-50/70 ${
                    highlightFeature && row.feature === highlightFeature
                      ? "bg-blue-100/80 ring-2 ring-inset ring-blue-400 even:bg-blue-100/80"
                      : ""
                  }`}
                >
                  {safeColumns.map(([key, , type], columnIndex) => {
                    const display = tableValue(row, key, type);
                    const numeric = Number(row?.[key]);
                    const isSignal = /(^iv$|correlation|vif|outlier_rate)/i.test(key) && Number.isFinite(numeric);
                    const isStatus = type === "boolean" || /status|monotonicity|informative/i.test(key);
                    const width = isSignal && scaleByKey[key] > 0 ? Math.max(3, Math.min(100, (Math.abs(numeric) / scaleByKey[key]) * 100)) : 0;
                    return (
                      <td
                        key={key}
                        className={`${columnIndex === 0 ? "sticky left-0 z-10 min-w-44 bg-white font-semibold text-slate-950 group-even:bg-slate-50 group-hover:bg-blue-50" : "text-slate-700"} border-b border-slate-100 px-4 py-3 align-middle tabular-nums`}
                      >
                        {isStatus ? (
                          <span className={`inline-flex rounded-full border px-2 py-1 text-[10px] font-semibold ${statusClasses(display)}`}>{display}</span>
                        ) : isSignal ? (
                          <div className="min-w-24">
                            <div className="font-mono font-semibold text-slate-900">{display}</div>
                            <div className="mt-1.5 h-1.5 overflow-hidden rounded-full bg-slate-100">
                              <div className={`h-full rounded-full ${/vif/i.test(key) && numeric >= 10 ? "bg-rose-500" : /vif/i.test(key) && numeric >= 5 ? "bg-amber-500" : "bg-blue-600"}`} style={{ width: `${width}%` }} />
                            </div>
                          </div>
                        ) : type === "percent" ? (
                          <span className="font-mono font-medium text-slate-800">{display}</span>
                        ) : (
                          <span className={typeof row?.[key] === "number" ? "font-mono text-slate-800" : ""}>{display}</span>
                        )}
                      </td>
                    );
                  })}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}

function CorrelationGrid({ columns, matrix }: { columns: string[]; matrix: Array<Array<number | null>> }) {
  const safeColumns = safeArray<string>(columns);
  const safeMatrix = safeArray<Array<number | null>>(matrix);
  if (!safeColumns.length) return <div className="flex min-h-52 items-center justify-center rounded-lg border border-slate-200 bg-white text-sm text-slate-500">At least two numeric predictors are required.</div>;
  return (
    <div className="overflow-auto rounded-lg border border-slate-200 bg-white p-3">
      <div className="grid min-w-[680px] gap-0.5" style={{ gridTemplateColumns: `160px repeat(${safeColumns.length}, minmax(34px, 1fr))` }}>
        <div />
        {safeColumns.map((column) => <div key={`head-${column}`} className="truncate px-1 py-2 text-center text-[10px] font-semibold text-slate-500" title={column}>{column}</div>)}
        {safeColumns.flatMap((rowName, rowIndex) => [
          <div key={`row-${rowName}`} className="truncate px-2 py-2 text-[11px] font-medium text-slate-700" title={rowName}>{rowName}</div>,
          ...safeColumns.map((column, columnIndex) => {
            const value = Number(safeMatrix[rowIndex]?.[columnIndex]);
            const magnitude = Number.isFinite(value) ? Math.abs(value) : 0;
            const color = value >= 0 ? `rgba(37, 99, 235, ${0.08 + magnitude * 0.75})` : `rgba(190, 24, 93, ${0.08 + magnitude * 0.65})`;
            return <div key={`${rowName}-${column}`} className="flex min-h-9 items-center justify-center text-[10px] tabular-nums text-slate-950" style={{ backgroundColor: color }} title={`${rowName} / ${column}: ${formatNumber(value, 3)}`}>{formatNumber(value, 2)}</div>;
          }),
        ])}
      </div>
    </div>
  );
}

function VifBarChart({ rows }: { rows: any[] }) {
  const prepared = safeArray<any>(rows).map((row) => {
    const rawValue = row.vif;
    const value = rawValue === null || rawValue === undefined || rawValue === "" ? Number.NaN : Number(rawValue);
    return { ...row, numericVif: Number.isFinite(value) ? value : null };
  }).sort((left, right) => {
    if (left.numericVif === null && right.numericVif === null) return 0;
    if (left.numericVif === null) return -1;
    if (right.numericVif === null) return 1;
    return right.numericVif - left.numericVif;
  }).slice(0, 15);
  if (!prepared.length) {
    return <div className="atlas-workflow-section flex min-h-64 items-center justify-center text-sm text-slate-500">VIF requires at least two eligible numeric predictors.</div>;
  }
  const largestFinite = Math.max(10, ...prepared.map((row) => row.numericVif ?? 10));
  const scaleMax = Math.min(50, Math.max(12, Math.ceil(largestFinite * 1.1)));
  const thresholdPosition = (value: number) => `${Math.min(100, (value / scaleMax) * 100)}%`;
  return (
    <div className="atlas-workflow-section overflow-hidden p-0">
      <div className="border-b border-slate-200 px-4 py-3">
        <div className="text-sm font-semibold text-slate-950">VIF Risk Map</div>
        <div className="mt-1 text-xs text-slate-500">The highest 15 factors are shown. VIF 5 requires review; VIF 10 indicates material multicollinearity.</div>
      </div>
      <div className="p-4">
        <div className="mb-3 flex flex-wrap gap-3 text-[11px] font-semibold">
          <span className="flex items-center gap-1.5 text-emerald-700"><span className="h-2.5 w-2.5 rounded-sm bg-emerald-500" /> Acceptable &lt; 5</span>
          <span className="flex items-center gap-1.5 text-amber-700"><span className="h-2.5 w-2.5 rounded-sm bg-amber-500" /> Review 5-10</span>
          <span className="flex items-center gap-1.5 text-red-700"><span className="h-2.5 w-2.5 rounded-sm bg-red-500" /> High &ge; 10</span>
        </div>
        <div className="mb-2 grid grid-cols-[minmax(130px,210px)_1fr_64px] gap-3 text-[10px] font-semibold uppercase text-slate-500">
          <span>Predictor</span>
          <span className="relative h-4"><span className="absolute left-0">0</span><span className="absolute -translate-x-1/2" style={{ left: thresholdPosition(5) }}>5</span><span className="absolute -translate-x-1/2" style={{ left: thresholdPosition(10) }}>10</span><span className="absolute right-0">{scaleMax}</span></span>
          <span className="text-right">VIF</span>
        </div>
        <div className="space-y-2.5">
          {prepared.map((row, index) => {
            const value = row.numericVif;
            const plotted = value === null ? scaleMax : Math.min(scaleMax, value);
            const status = String(row.status ?? (plotted >= 10 ? "high" : plotted >= 5 ? "review" : "acceptable"));
            const color = status === "high" ? "bg-red-500" : status === "review" ? "bg-amber-500" : "bg-emerald-500";
            return (
              <div key={`${row.feature}-${index}`} className="grid grid-cols-[minmax(130px,210px)_1fr_64px] items-center gap-3">
                <span className="truncate text-xs font-medium text-slate-800" title={String(row.feature)}>{row.feature}</span>
                <div className="relative h-4 overflow-hidden rounded bg-slate-100">
                  <span className="absolute inset-y-0 border-l border-amber-400" style={{ left: thresholdPosition(5) }} />
                  <span className="absolute inset-y-0 border-l border-red-400" style={{ left: thresholdPosition(10) }} />
                  <span className={`block h-full rounded ${color}`} style={{ width: `${Math.max(1.5, (plotted / scaleMax) * 100)}%` }} />
                </div>
                <span className={`text-right font-mono text-xs font-semibold ${status === "high" ? "text-red-700" : status === "review" ? "text-amber-700" : "text-emerald-700"}`}>{value === null ? `>${scaleMax}` : formatNumber(value, 2)}</span>
              </div>
            );
          })}
        </div>
      </div>
    </div>
  );
}

function titleCase(value: string) {
  return value ? `${value.charAt(0).toUpperCase()}${value.slice(1)}` : "Not available";
}
