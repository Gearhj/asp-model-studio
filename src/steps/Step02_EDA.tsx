import React, { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Link } from "react-router-dom";
import {
  Activity,
  AlertTriangle,
  ArrowRight,
  BarChart3,
  CheckCircle2,
  CircleAlert,
  Database,
  Download,
  FileText,
  FileSearch,
  GitCompareArrows,
  Layers3,
  LoaderCircle,
  RefreshCw,
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
  type AtlasDataScope,
} from "../components/ui/AtlasWorkflow";
import { createEvidence } from "../lib/evidenceGraph";
import { logDecision } from "../lib/decisionJournal";
import {
  buildCanonicalEvidenceEnvelope,
  canonicalDatasetStorageKey,
  type CanonicalDatasetIdentity,
} from "../lib/datasetIdentity";
import { usePredictiveIdentity } from "../components/PredictiveIdentityProvider";
import {
  assertExactEdaResponseLineage,
  buildCanonicalEdaRequestContract,
  DataAcquisitionEdaHandoffError,
  fetchCanonicalDataAcquisitionEdaHandoff,
  type CanonicalDataAcquisitionEdaHandoff,
} from "../lib/dataAcquisitionEdaHandoff";
import { useWorkflowStore } from "../state/useWorkflowStore";
import { formatNullableMetric, safeArray, safeObject } from "../lib/workflowSafety";
import TargetIntelligenceWorkspace from "../components/eda/TargetIntelligenceWorkspace";
import FindingsDecisionWorkspace from "../components/eda/FindingsDecisionWorkspace";
import type { PredictorOption } from "../components/eda/TargetByPredictorPanel";
import PredictorDistributionExplorer from "../components/eda/visual/PredictorDistributionExplorer";
import {
  LazyPredictorSecondaryInsights,
  PredictorSignalLandscape,
} from "../components/eda/visual/PredictorVisualSuite";
import CorrelationExplorer from "../components/eda/visual/CorrelationExplorer";
import VifExplorer, {
  type VifSimulationRequest,
  type VifSimulationResult,
} from "../components/eda/visual/VifExplorer";
import BureauSemanticContextPanel from "../components/BureauSemanticContextPanel";
import {
  useEdaVisualSelection,
  type EdaNumericRange,
} from "../state/useEdaVisualSelection";
import { recordEdaPerformance } from "../visual-intelligence/performance";
import { writeEdaCodeContextSeed } from "../lib/codeContextSafety";
import {
  confirmEdaDocumentation,
  EdaDocumentationRequestError,
  getEdaDocumentationState,
  saveEdaDocumentationDraft,
  type EdaDocumentationEvidenceReference,
  type EdaDocumentationState,
} from "../lib/edaDocumentationApi";
import {
  buildEdaDocumentationPayload,
  hydrateEdaFindingsFromDocumentation,
} from "../lib/edaDocumentationPayload";
import {
  type EdaFindingsReviewState,
} from "../lib/edaFindings";
import {
  buildGovernedFindingEvidencePayload,
  generateEdaParentFindings,
  summarizeFindingGovernance,
} from "../lib/edaFindingGovernance";
import {
  buildEdaTabBadges,
  edaTabStorageKey,
  isEdaOverallStatusEligible,
  persistEdaWorkspaceTab,
  readEdaWorkspaceTab,
  summarizeEdaCompletionBlockers,
  tabForKeyboardNavigation,
  type EdaCompletionBlocker,
  type EdaWorkspaceTab,
} from "../lib/edaWorkspaceNavigation";
import { readBlockedEdaWorkspaceReadiness } from "../lib/edaWorkspaceReadiness";
import { projectWorkflowRoute } from "../lib/projectScopedRoutes";
import {
  normalizeVifResolutionPlan,
  type VifResolutionDecisionRequest,
  type VifResolutionInputs,
  type VifResolutionPlan,
} from "../lib/vifResolutionPlan";
import "../components/eda/eda-premium.css";

const RelationshipExplorer = React.lazy(
  () => import("../components/eda/visual/RelationshipExplorer"),
);

const API_BASE =
  (import.meta.env.VITE_API_BASE as string | undefined)?.replace(/\/$/, "") ||
  "http://127.0.0.1:8001/api";

const FINDINGS_KEY_PREFIX = "atlas-predictive-eda-findings-v2";
const DOCUMENTATION_SECTIONS: EDATab[] = [
  "overview",
  "target",
  "predictors",
  "relationships",
  "stability",
  "findings",
];

type EDATab = EdaWorkspaceTab;
type Scope = AtlasDataScope;

type WorkspaceResponse = {
  ok: boolean;
  project_id: string;
  dataset_id: string;
  dataset_version_id: string;
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

type FindingsState = EdaFindingsReviewState;

type EDAErrorState = {
  message: string;
  endpoint: string;
  status?: number;
  code?: string;
  recovery?: string;
  technical?: string;
  domain:
    | "analysis_partition"
    | "identity"
    | "authorization"
    | "route"
    | "server"
    | "transport";
  retryable?: boolean;
};

const EDA_READINESS_GUIDANCE: Record<
  string,
  { title: string; message: string; recovery: string; domain: EDAErrorState["domain"] }
> = {
  analysis_partition_required: {
    title: "Analysis Partition confirmation required",
    message: "The registered dataset is active, but its governed development and final-holdout partition has not been confirmed.",
    recovery: "Return to Data Acquisition, choose the governed development/final-holdout ratio, and confirm it explicitly.",
    domain: "analysis_partition",
  },
  analysis_partition_stale: {
    title: "Analysis Partition is stale",
    message: "The governed dataset, target contract, or predictor authorization changed after this Analysis Partition was sealed.",
    recovery: "Return to Data Acquisition and confirm a current Analysis Partition for the exact active identity.",
    domain: "analysis_partition",
  },
  analysis_partition_contradictory: {
    title: "Analysis Partition identity conflict",
    message: "The stored Analysis Partition does not match the exact active dataset and target contract.",
    recovery: "Return to Data Acquisition and resolve the displayed Analysis Partition identity conflict.",
    domain: "analysis_partition",
  },
  predictor_authorization_required: {
    title: "Predictor authorization required",
    message: "EDA cannot begin until the governed predictor set is authorized for the development population.",
    recovery: "Return to Data Acquisition, approve eligible predictors, and confirm the Analysis Partition.",
    domain: "analysis_partition",
  },
  target_contract_stale: {
    title: "Target contract is not current",
    message: "The target or event mapping no longer matches the sealed Analysis Partition.",
    recovery: "Return to Data Acquisition, confirm the target mapping, and then confirm the Analysis Partition.",
    domain: "analysis_partition",
  },
  dataset_identity_unavailable: {
    title: "Governed dataset identity unavailable",
    message: "EDA could not verify the exact active Dataset Library version for this project.",
    recovery: "Return to Data Acquisition and explicitly activate the exact linked dataset version.",
    domain: "identity",
  },
  analysis_partition_integrity_failed: {
    title: "Analysis Partition integrity check failed",
    message: "The sealed row assignment or holdout-isolation checksum could not be verified.",
    recovery: "Stop analysis and ask an administrator to review the governed partition artifact.",
    domain: "analysis_partition",
  },
  dataset_identity_required: {
    title: "Registered dataset activation required",
    message: "EDA requires one exact active Dataset Library version for this project.",
    recovery: "Return to Data Acquisition and activate the intended registered dataset version.",
    domain: "identity",
  },
  target_contract_required: {
    title: "Target contract confirmation required",
    message: "EDA requires the target, class mapping, and predictor authorization from Data Acquisition.",
    recovery: "Return to Data Acquisition and confirm the target mapping and eligible predictors.",
    domain: "authorization",
  },
  special_value_review_incomplete: {
    title: "Special-Value Treatment Review is incomplete",
    message: "The governed Special-Value Treatment Review must be confirmed before EDA can open.",
    recovery: "Return to Data Acquisition and resolve the first remaining special-value treatment item.",
    domain: "authorization",
  },
  special_value_review_required: {
    title: "Special-Value Treatment Review is incomplete",
    message: "The governed Special-Value Treatment Review must be confirmed before EDA can open.",
    recovery: "Return to Data Acquisition and resolve the first remaining special-value treatment item.",
    domain: "authorization",
  },
  special_value_review_stale: {
    title: "Special-Value Treatment Review is stale",
    message: "The saved special-value decisions no longer match the current Data Acquisition lineage.",
    recovery: "Return to Data Acquisition and reconfirm the review for the current activation and predictor authorization.",
    domain: "authorization",
  },
  eda_canonical_lineage_required: {
    title: "Complete Data Acquisition handoff required",
    message: "EDA requires the exact current dataset, target, predictor authorization, Special-Value Review, and Analysis Partition lineage.",
    recovery: "Open EDA from the final project-scoped Data Acquisition continuation action.",
    domain: "identity",
  },
  dataset_activation_revision_stale: {
    title: "Dataset activation changed",
    message: "A newer activation revision replaced the one carried by this EDA request.",
    recovery: "Reload the project and retry from the current Data Acquisition contract.",
    domain: "identity",
  },
  data_acquisition_handoff_mismatch: {
    title: "Data Acquisition handoff is stale",
    message: "The EDA request no longer matches the exact backend-authoritative Data Acquisition contract.",
    recovery: "Reload Data Acquisition and verify the current dataset, target, predictor authorization, and Analysis Partition.",
    domain: "identity",
  },
};

function normalizeEdaRequestError(input: {
  endpoint: string;
  status: number;
  payload: unknown;
  section: EDATab;
}): EDAErrorState {
  const envelope = safeObject(input.payload);
  const rawDetail = envelope.detail;
  const detail = safeObject(rawDetail);
  const code = String(
    detail.code ??
      envelope.code ??
      (input.status === 404 ? "eda_route_unavailable" : "eda_request_failed"),
  );
  const guidance = EDA_READINESS_GUIDANCE[code];
  const rawMessage =
    (typeof rawDetail === "string" ? rawDetail : detail.message ?? detail.detail) ??
    envelope.message ??
    envelope.error;

  if (guidance) {
    return {
      endpoint: input.endpoint,
      status: input.status,
      code,
      domain: guidance.domain,
      message: String(rawMessage ?? guidance.message),
      recovery: String(detail.recovery ?? envelope.recovery ?? guidance.recovery),
      retryable: code !== "analysis_partition_integrity_failed",
      technical: JSON.stringify(input.payload ?? { status: input.status }, null, 2),
    };
  }
  if (input.status === 401 || input.status === 403) {
    return {
      endpoint: input.endpoint,
      status: input.status,
      code,
      domain: "authorization",
      message: String(rawMessage ?? "Your session is not authorized to load governed EDA."),
      recovery: "Sign in again or ask a project administrator to confirm access.",
      retryable: true,
    };
  }
  if (input.status === 404) {
    return {
      endpoint: input.endpoint,
      status: input.status,
      code,
      domain: "route",
      message: String(rawMessage ?? "The EDA backend route is unavailable."),
      recovery: "Confirm the running FastAPI backend includes the EDA router, then retry.",
      retryable: true,
    };
  }
  if (input.status === 409) {
    return {
      endpoint: input.endpoint,
      status: input.status,
      code,
      domain: "analysis_partition",
      message: String(rawMessage ?? "The governed EDA analytical prerequisites are not current."),
      recovery: String(
        detail.recovery ??
          envelope.recovery ??
          "Return to Data Acquisition and confirm the current Analysis Partition.",
      ),
      retryable: true,
      technical: JSON.stringify(input.payload ?? { status: input.status }, null, 2),
    };
  }
  return {
    endpoint: input.endpoint,
    status: input.status,
    code,
    domain: input.status >= 500 ? "server" : "transport",
    message: String(rawMessage ?? `EDA ${input.section} analysis failed.`),
    recovery:
      input.status >= 500
        ? "The governed identity remains selected. Retry the analysis; if the error persists, review the safe server log."
        : "Review the request and retry.",
    retryable: true,
    technical: JSON.stringify(input.payload ?? { status: input.status }, null, 2),
  };
}

type EdaQuickSummaryItem = {
  label: string;
  value: string;
  tone?: "neutral" | "info" | "success" | "warning" | "danger";
};

const tabs: Array<{ id: EDATab; label: string; icon: LucideIcon }> = [
  { id: "overview", label: "Overview", icon: Database },
  { id: "target", label: "Target", icon: Target },
  { id: "predictors", label: "Predictors", icon: BarChart3 },
  { id: "relationships", label: "Relationships", icon: GitCompareArrows },
  { id: "stability", label: "Stability & Segments", icon: ShieldCheck },
  { id: "findings", label: "Findings", icon: FileSearch },
];

const predictorSectionLinks = [
  { id: "eda-predictors-signal", label: "Signal" },
  { id: "eda-predictors-deep-dive", label: "Deep Dive" },
  { id: "eda-predictors-shape-gallery", label: "Shape Gallery" },
  { id: "eda-predictors-quality-matrix", label: "Quality Matrix" },
  { id: "eda-predictors-special-values", label: "Special Values" },
  { id: "eda-predictors-inventory", label: "Inventory" },
];

const relationshipSectionLinks = [
  { id: "eda-relationships-correlation", label: "Correlation" },
  { id: "eda-relationships-strong-pairs", label: "Strong Pairs" },
  { id: "eda-relationships-vif", label: "VIF" },
  { id: "eda-relationships-resolution-plan", label: "Resolution Plan" },
  { id: "eda-relationship-explorer-section", label: "Visual Explorer" },
  { id: "eda-relationships-pairwise-plot", label: "Pairwise Plot" },
];

const documentationImpactByTab: Record<
  EDATab,
  { title: string; detail: string }
> = {
  overview: {
    title: "Population, quality, and readiness",
    detail:
      "The governed population, predictor inventory, integrity signals, exclusions, and readiness assessment will populate the EDA overview narrative.",
  },
  target: {
    title: "Target definition and prevalence",
    detail:
      "Target lineage, class balance, uncertainty, quality, leakage review, and target-by-predictor findings will populate the target narrative.",
  },
  predictors: {
    title: "Predictor evidence and notable findings",
    detail:
      "Authorized predictors, distribution summaries, missingness, IV, monotonicity, and reviewer findings will populate the predictor narrative.",
  },
  relationships: {
    title: "Correlation, VIF, and relationship decisions",
    detail:
      "Pinned correlations, multicollinearity review, bounded relationship exploration, and retain/drop/combine rationale will populate the relationships narrative.",
  },
  stability: {
    title: "Stability and segment availability",
    detail:
      "Available time or segment analysis—or the explicit governed not-available statement—will populate the stability narrative.",
  },
  findings: {
    title: "Reviewer decisions and evidence",
    detail:
      "Duplicate treatment, approved findings, unresolved items, commentary, and evidence references will populate the findings narrative.",
  },
};

function readFindings(
  identity: CanonicalDatasetIdentity | null,
  storageKey = "",
): FindingsState {
  if (!identity || !storageKey) {
    return { commentary: "", status: "draft", duplicateTreatment: "review" };
  }
  try {
    const parsed = JSON.parse(localStorage.getItem(storageKey) || "null");
    if (parsed && typeof parsed.commentary === "string") {
      return {
        ...parsed,
        duplicateTreatment:
          parsed.duplicateTreatment === "exclude" || parsed.duplicateTreatment === "keep"
            ? parsed.duplicateTreatment
            : "review",
      };
    }
  } catch {
    // Invalid prior browser state should not block governed backend analysis.
  }
  return { commentary: "", status: "draft", duplicateTreatment: "review" };
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
  const {
    readiness: identityReadiness,
    dataAcquisitionContextReadiness,
  } = usePredictiveIdentity();
  const datasetIdentity =
    identityReadiness.status === "ready" &&
    identityReadiness.projectId === projectId
      ? identityReadiness.identity
      : null;
  const datasetIdentityError =
    identityReadiness.projectId === projectId
      ? identityReadiness.message
      : "The exact registered Dataset Library version is still being resolved for this project.";
  const [canonicalHandoff, setCanonicalHandoff] =
    useState<CanonicalDataAcquisitionEdaHandoff | null>(null);
  const [handoffLoading, setHandoffLoading] = useState(true);
  const [handoffError, setHandoffError] = useState<EDAErrorState | null>(null);
  const handoffSequence = useRef(0);
  const currentReproducibilityContext =
    dataAcquisitionContextReadiness.status === "ready" &&
    dataAcquisitionContextReadiness.projectId === projectId &&
    dataAcquisitionContextReadiness.context?.state === "current"
      ? dataAcquisitionContextReadiness.context
      : null;
  const activeCanonicalHandoff =
    !handoffLoading &&
    canonicalHandoff &&
    currentReproducibilityContext &&
    datasetIdentity &&
    canonicalHandoff.context.context_id ===
      currentReproducibilityContext.context_id &&
    canonicalHandoff.context.target_contract.target_contract_id ===
      currentReproducibilityContext.target_contract?.target_contract_id &&
    canonicalHandoff.context.predictor_authorization
      .predictor_authorization_id ===
      currentReproducibilityContext.predictor_authorization
        ?.predictor_authorization_id &&
    canonicalHandoff.context.analysis_partition.analysis_partition_id ===
      currentReproducibilityContext.analysis_partition?.analysis_partition_id &&
    canonicalHandoff.context.analysis_partition.revision ===
      currentReproducibilityContext.analysis_partition?.revision &&
    canonicalHandoff.datasetIdentity.project_id === projectId &&
    canonicalHandoff.datasetIdentity.dataset_id === datasetIdentity.dataset_id &&
    canonicalHandoff.datasetIdentity.dataset_version_id ===
      datasetIdentity.dataset_version_id &&
    canonicalHandoff.datasetIdentity.activation_revision ===
      datasetIdentity.activation_revision
      ? canonicalHandoff
      : null;
  const activeHandoffKey = activeCanonicalHandoff
    ? JSON.stringify(buildCanonicalEdaRequestContract(activeCanonicalHandoff))
    : "";
  const activeHandoffKeyRef = useRef("");
  activeHandoffKeyRef.current = activeHandoffKey;
  const findingsStorageKey = useMemo(
    () =>
      datasetIdentity && activeCanonicalHandoff
        ? `${canonicalDatasetStorageKey(
            FINDINGS_KEY_PREFIX,
            datasetIdentity,
          )}:${encodeURIComponent(activeHandoffKey)}`
        : "",
    [activeCanonicalHandoff, activeHandoffKey, datasetIdentity],
  );
  const edaTabPreferenceKey = useMemo(
    () =>
      edaTabStorageKey({
        projectId,
        datasetId: datasetIdentity?.dataset_id,
        datasetVersionId: datasetIdentity?.dataset_version_id,
      }),
    [
      datasetIdentity?.dataset_id,
      datasetIdentity?.dataset_version_id,
      projectId,
    ],
  );
  const [activeTab, setActiveTab] = useState<EDATab>(() =>
    readEdaWorkspaceTab({
      search: typeof window === "undefined" ? "" : window.location.search,
      storage: typeof localStorage === "undefined" ? null : localStorage,
      storageKey: edaTabPreferenceKey,
    }),
  );
  const [sections, setSections] = useState<Partial<Record<EDATab, WorkspaceResponse>>>({});
  const [loading, setLoading] = useState<EDATab | null>(null);
  const [error, setError] = useState<EDAErrorState | null>(null);
  const [segmentField, setSegmentField] = useState("");
  const [dateField, setDateField] = useState("");
  const [pairwiseFeatures, setPairwiseFeatures] = useState<string[]>([]);
  const [histogramBins, setHistogramBins] = useState(20);
  const [findings, setFindings] = useState<FindingsState>(() =>
    readFindings(datasetIdentity, findingsStorageKey),
  );
  const [evidenceMessage, setEvidenceMessage] = useState("");
  const [documentationState, setDocumentationState] =
    useState<EdaDocumentationState | null>(null);
  const [documentationHydrated, setDocumentationHydrated] = useState(false);
  const [documentationMessage, setDocumentationMessage] = useState("");
  const [confirmationPending, setConfirmationPending] = useState(false);
  const [documentationEvidence, setDocumentationEvidence] = useState<
    EdaDocumentationEvidenceReference[]
  >([]);
  const requestSequence = useRef<Partial<Record<EDATab, number>>>({});
  const tabRefs = useRef<Partial<Record<EDATab, HTMLButtonElement | null>>>({});
  const documentationDraftTimer = useRef<number | null>(null);
  const lastDraftVersion = useRef("");
  const shellStartedAt = useRef(
    typeof performance === "undefined" ? 0 : performance.now(),
  );
  const firstUsefulChartRecorded = useRef(false);
  const compactPreambleRef = useRef<HTMLDivElement>(null);
  const firstAnalyticalContentRef = useRef<HTMLDivElement>(null);
  const [compactPreambleHeight, setCompactPreambleHeight] = useState<
    number | null
  >(null);
  const [stickyTopOffset, setStickyTopOffset] = useState(120);
  const selectedVariable = useEdaVisualSelection((state) => state.selectedVariable);
  const selectedRange = useEdaVisualSelection((state) => state.selectedRange);
  const pinnedPair = useEdaVisualSelection((state) => state.pinnedPair);
  const relationshipAxes = useEdaVisualSelection((state) => state.relationshipAxes);
  const setSelectionScope = useEdaVisualSelection((state) => state.setScope);
  const clearVisualSelection = useEdaVisualSelection((state) => state.clearSelection);

  useEffect(() => {
    const sequence = ++handoffSequence.current;
    const controller = new AbortController();
    for (const tab of tabs) {
      requestSequence.current[tab.id] =
        (requestSequence.current[tab.id] ?? 0) + 1;
    }
    setSections({});
    setCanonicalHandoff(null);
    setHandoffError(null);

    if (!datasetIdentity) {
      setHandoffLoading(false);
      setHandoffError({
        endpoint: `${API_BASE}/data/reproducibility-context`,
        code: "dataset_identity_required",
        domain: "identity",
        message: datasetIdentityError,
        recovery:
          "Return to Data Acquisition and activate the exact registered Dataset Library version.",
      });
      return () => controller.abort();
    }
    if (
      dataAcquisitionContextReadiness.status === "idle" ||
      dataAcquisitionContextReadiness.status === "loading"
    ) {
      setHandoffLoading(true);
      return () => controller.abort();
    }
    if (
      dataAcquisitionContextReadiness.status === "error" ||
      !dataAcquisitionContextReadiness.context
    ) {
      setHandoffLoading(false);
      setHandoffError({
        endpoint: `${API_BASE}/data/reproducibility-context`,
        code: "data_acquisition_handoff_mismatch",
        domain: "identity",
        message: dataAcquisitionContextReadiness.message,
        recovery:
          "Reload Data Acquisition and verify the exact current governed contract.",
        retryable: true,
      });
      return () => controller.abort();
    }

    setHandoffLoading(true);
    void fetchCanonicalDataAcquisitionEdaHandoff({
      projectId,
      expectedIdentity: datasetIdentity,
      context: dataAcquisitionContextReadiness.context,
      signal: controller.signal,
    })
      .then((handoff) => {
        if (controller.signal.aborted || sequence !== handoffSequence.current) return;
        setCanonicalHandoff(handoff);
        setHandoffError(null);
      })
      .catch((cause) => {
        if (controller.signal.aborted || sequence !== handoffSequence.current) return;
        const handoffCause =
          cause instanceof DataAcquisitionEdaHandoffError ? cause : null;
        const guidance = handoffCause
          ? EDA_READINESS_GUIDANCE[handoffCause.code]
          : null;
        setHandoffError({
          endpoint: `${API_BASE}/data/reproducibility-context`,
          code: handoffCause?.code ?? "data_acquisition_handoff_mismatch",
          domain: guidance?.domain ?? "identity",
          message:
            handoffCause?.message ??
            (cause instanceof Error
              ? cause.message
              : "ATLAS could not validate the Data Acquisition handoff."),
          recovery:
            handoffCause?.recovery ??
            "Reload Data Acquisition and verify the exact current governed contract.",
          retryable: true,
        });
      })
      .finally(() => {
        if (!controller.signal.aborted && sequence === handoffSequence.current) {
          setHandoffLoading(false);
        }
      });
    return () => controller.abort();
  }, [
    dataAcquisitionContextReadiness.context,
    dataAcquisitionContextReadiness.message,
    dataAcquisitionContextReadiness.projectId,
    dataAcquisitionContextReadiness.status,
    datasetIdentity?.activation_revision,
    datasetIdentity?.dataset_id,
    datasetIdentity?.dataset_version_id,
    datasetIdentity?.project_id,
    datasetIdentityError,
    projectId,
  ]);

  const overview = activeCanonicalHandoff ? sections.overview : undefined;
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

  const canonicalRequestContract = useMemo(
    () => activeCanonicalHandoff
      ? buildCanonicalEdaRequestContract(activeCanonicalHandoff)
      : null,
    [activeCanonicalHandoff],
  );
  const requestBody = useMemo(
    () => ({
      ...(canonicalRequestContract ?? { project_id: projectId }),
      problem_type: overview?.problem_type,
      selected_features:
        activeCanonicalHandoff?.context.predictor_authorization
          .authorized_predictors ?? [],
      pairwise_features: pairwiseFeatures,
      segment_field: segmentField || undefined,
      date_field: dateField || undefined,
      histogram_bins: histogramBins,
      predictor_visual_shape_limit: 8,
      rendered_sample_limit: 5000,
    }),
    [activeCanonicalHandoff, canonicalRequestContract, dateField, histogramBins, overview?.problem_type, pairwiseFeatures, projectId, segmentField],
  );

  async function loadSection(
    section: EDATab,
    force = false,
    overrides: Record<string, unknown> = {},
  ): Promise<WorkspaceResponse | null> {
    const requestHandoff = activeCanonicalHandoff;
    if (!requestHandoff) {
      setError({
        endpoint: `${API_BASE}/eda/workspace/${section}`,
        code: handoffError?.code ?? "data_acquisition_handoff_mismatch",
        domain: handoffError?.domain ?? "identity",
        message:
          handoffError?.message ??
          "ATLAS is still verifying the exact Data Acquisition contract.",
        recovery:
          handoffError?.recovery ??
          "Wait for the backend-authoritative handoff, then retry.",
      });
      return null;
    }
    if (!force && sections[section]) return sections[section] ?? null;
    const endpoint = `${API_BASE}/eda/workspace/${section}`;
    const sequence = (requestSequence.current[section] ?? 0) + 1;
    requestSequence.current[section] = sequence;
    const requestHandoffKey = JSON.stringify(
      buildCanonicalEdaRequestContract(requestHandoff),
    );
    setLoading(section);
    setError(null);
    const startedAt = typeof performance === "undefined" ? 0 : performance.now();
    try {
      const response = await fetch(endpoint, {
        method: "POST",
        credentials: "include",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          ...requestBody,
          ...overrides,
          ...buildCanonicalEdaRequestContract(requestHandoff),
        }),
      });
      const payload = await response.json().catch(() => null);
      if (
        requestSequence.current[section] !== sequence ||
        activeHandoffKeyRef.current !== requestHandoffKey
      ) return null;
      if (!response.ok || !payload?.ok) {
        setError(
          normalizeEdaRequestError({
            endpoint,
            status: response.status,
            payload,
            section,
          }),
        );
        return null;
      }
      assertExactEdaResponseLineage(requestHandoff, payload);
      const blockedReadiness = readBlockedEdaWorkspaceReadiness(payload);
      if (blockedReadiness) {
        const guidance = EDA_READINESS_GUIDANCE[blockedReadiness.code];
        // HTTP 200 structural-only readiness is not an analytical Overview.
        // Clear any previously loaded analysis and documentation so neither can
        // render or restart while the Analysis Partition is blocked.
        setSections({});
        setDocumentationState(null);
        setDocumentationEvidence([]);
        setDocumentationMessage("");
        setDocumentationHydrated(true);
        lastDraftVersion.current = "";
        setError({
          endpoint,
          status: response.status,
          code: blockedReadiness.code,
          domain: guidance?.domain ?? "analysis_partition",
          message: blockedReadiness.message,
          recovery: blockedReadiness.recovery,
          retryable:
            blockedReadiness.code !== "analysis_partition_integrity_failed",
          technical: JSON.stringify(
            {
              response_mode: "partial_readiness",
              code: blockedReadiness.code,
              target_directed_available: false,
              structural_overview_available:
                blockedReadiness.structuralOverviewAvailable,
              final_holdout_accessed: blockedReadiness.finalHoldoutAccessed,
              stale_artifacts: blockedReadiness.staleArtifacts,
            },
            null,
            2,
          ),
        });
        return null;
      }
      writeEdaCodeContextSeed(projectId, {
        datasetId: requestHandoff.datasetIdentity.dataset_id,
        datasetVersion: requestHandoff.datasetIdentity.dataset_version_id,
        datasetName:
          requestHandoff.context.identity.dataset_name,
        target: String(payload.target ?? ""),
        predictorManifestId: String(
          payload.predictor_authorization?.manifest_version ?? "",
        ),
        generatedAt: String(
          payload.generated_at ?? new Date().toISOString(),
        ),
      });
      setSections((current) => ({ ...current, [section]: payload as WorkspaceResponse }));
      recordEdaPerformance("full-tab-readiness", startedAt, {
        section,
        serverDurationMs: payload.duration_ms,
        cacheStatus: payload.cache_status,
      });
      if (!firstUsefulChartRecorded.current) {
        firstUsefulChartRecorded.current = true;
        recordEdaPerformance("first-useful-chart", shellStartedAt.current, {
          section,
          datasetVersion: payload.dataset_version,
        });
      }
      return payload as WorkspaceResponse;
    } catch (cause) {
      if (
        requestSequence.current[section] !== sequence ||
        activeHandoffKeyRef.current !== requestHandoffKey
      ) return null;
      if (cause instanceof DataAcquisitionEdaHandoffError) {
        setError({
          endpoint,
          code: cause.code,
          domain: EDA_READINESS_GUIDANCE[cause.code]?.domain ?? "identity",
          message: cause.message,
          recovery: cause.recovery,
          retryable: true,
        });
      } else {
        setError({
          endpoint,
          code: "eda_backend_unavailable",
          domain: "transport",
          message: cause instanceof Error ? cause.message : "ATLAS could not load this EDA section.",
          recovery: "Confirm the FastAPI backend is running, then retry the exact governed request.",
          retryable: true,
        });
      }
      return null;
    } finally {
      if (requestSequence.current[section] === sequence) setLoading(null);
    }
  }

  useEffect(() => {
    const frame = window.requestAnimationFrame(() => {
      recordEdaPerformance("initial-page-shell", shellStartedAt.current, {
        route: "/step02",
      });
    });
    return () => window.cancelAnimationFrame(frame);
  }, []);

  useEffect(() => {
    setActiveTab(
      readEdaWorkspaceTab({
        search: window.location.search,
        storage: localStorage,
        storageKey: edaTabPreferenceKey,
      }),
    );
  }, [edaTabPreferenceKey]);

  useEffect(() => {
    const nextRoute = persistEdaWorkspaceTab({
      tab: activeTab,
      storage: localStorage,
      storageKey: edaTabPreferenceKey,
      currentUrl: window.location.href,
    });
    if (nextRoute) {
      window.history.replaceState(window.history.state, "", nextRoute);
    }
  }, [activeTab, edaTabPreferenceKey]);

  useEffect(() => {
    const restoreRouteTab = () => {
      setActiveTab(
        readEdaWorkspaceTab({
          search: window.location.search,
          fallback: "overview",
        }),
      );
    };
    window.addEventListener("popstate", restoreRouteTab);
    return () => window.removeEventListener("popstate", restoreRouteTab);
  }, []);

  useEffect(() => {
    setFindings(readFindings(datasetIdentity, findingsStorageKey));
    setSections({});
    setDocumentationState(null);
    setDocumentationEvidence([]);
    lastDraftVersion.current = "";
    if (handoffLoading) return;
    if (!activeCanonicalHandoff) {
      setError(
        handoffError ?? {
          endpoint: `${API_BASE}/eda/workspace/overview`,
          code: "data_acquisition_handoff_mismatch",
          domain: "identity",
          message: "The backend-authoritative Data Acquisition handoff is unavailable.",
          recovery: "Return to Data Acquisition and resolve the displayed prerequisite.",
        },
      );
      return;
    }
    setError(null);
    void loadSection("overview", true);
    // Load once from the governed backend. Secondary sections remain lazy.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [
    activeCanonicalHandoff?.context.context_id,
    activeCanonicalHandoff?.specialValueReview.revision,
    findingsStorageKey,
    handoffLoading,
  ]);

  useEffect(() => {
    if (activeTab !== "overview" && activeCanonicalHandoff && overview) {
      void loadSection(activeTab, true);
    }
    // Configuration-specific refreshes are handled by explicit actions below.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [
    activeTab,
    activeCanonicalHandoff?.context.context_id,
    activeCanonicalHandoff?.specialValueReview.revision,
    overview,
  ]);

  useEffect(() => {
    if (activeTab !== "findings" || !sections.findings) return;
    let cancelled = false;
    const findingSources: EDATab[] = [
      "target",
      "predictors",
      "relationships",
      "stability",
    ];
    void (async () => {
      for (const section of findingSources) {
        if (cancelled) return;
        await loadSection(section);
      }
    })();
    return () => {
      cancelled = true;
    };
    // Findings consolidate already-governed section aggregates. Loading each
    // missing section once here avoids a blank-notebook first experience while
    // preserving the normal lazy behavior on every other EDA tab.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [activeTab, sections.findings]);

  useEffect(() => {
    if (!activeHandoffKey || !overview?.target) return;
    setSelectionScope(activeHandoffKey);
    setPairwiseFeatures([]);
  }, [activeHandoffKey, overview?.target, setSelectionScope]);

  useEffect(() => {
    let cancelled = false;
    const controller = new AbortController();
    setDocumentationHydrated(false);
    setDocumentationMessage("");
    if (!datasetIdentity) {
      setDocumentationMessage(datasetIdentityError);
      setDocumentationHydrated(true);
      return () => controller.abort();
    }
    // Documentation is downstream of the governed analytical contract. Do not
    // launch a parallel documentation request while the overview is blocked;
    // doing so previously let a secondary 500 obscure the actionable partition
    // 409 that the analyst needed to resolve first.
    if (!overview) {
      setDocumentationHydrated(true);
      return () => controller.abort();
    }
    getEdaDocumentationState(projectId, datasetIdentity, controller.signal)
      .then((state) => {
        if (cancelled) return;
        setDocumentationState(state);
        const source = state.draft ?? state.current_approved;
        if (source) {
          setFindings((browserDraft) =>
            hydrateEdaFindingsFromDocumentation(source, browserDraft),
          );
        }
        const evidence = source?.evidence_references ?? [];
        setDocumentationEvidence(evidence);
        lastDraftVersion.current = state.draft?.eda_analysis_version ?? "";
      })
      .catch((cause) => {
        if (cancelled || controller.signal.aborted) return;
        setDocumentationMessage(
          cause instanceof EdaDocumentationRequestError && cause.status === 409
            ? `${cause.message} ${cause.recovery || "Complete the current Analysis Partition and refresh EDA."}`.trim()
            : cause instanceof Error
            ? cause.message
            : "ATLAS could not load the governed EDA documentation state.",
        );
      })
      .finally(() => {
        if (!cancelled) setDocumentationHydrated(true);
      });
    return () => {
      cancelled = true;
      controller.abort();
    };
  }, [
    activeHandoffKey,
    datasetIdentity,
    datasetIdentityError,
    overview?.dataset_id,
    overview?.dataset_version_id,
    overview?.target,
    projectId,
  ]);

  const buildDocumentation = useCallback(
    (
      resolvedSections: Partial<Record<EDATab, WorkspaceResponse>> = sections,
      evidenceReferences: EdaDocumentationEvidenceReference[] =
        documentationEvidence,
    ) => {
      const resolvedOverview = resolvedSections.overview;
      const datasetId = String(datasetIdentity?.dataset_id ?? "").trim();
      const datasetVersion = String(
        datasetIdentity?.dataset_version_id ?? "",
      ).trim();
      const target = String(
        resolvedOverview?.target ??
          activeCanonicalHandoff?.context.target_contract.target ??
          "",
      ).trim();
      const predictorManifestId = String(
        resolvedOverview?.predictor_authorization?.manifest_version ?? "",
      ).trim();
      if (
        !resolvedOverview ||
        !datasetId ||
        !datasetVersion ||
        !target ||
        !predictorManifestId
      ) {
        return null;
      }
      return buildEdaDocumentationPayload({
        projectId,
        datasetId,
        datasetVersion,
        target,
        predictorManifestId,
        sections: resolvedSections,
        findings,
        selectedFeatures:
          activeCanonicalHandoff?.context.predictor_authorization
            .authorized_predictors ?? [],
        controls: {
          histogramBins,
          dateField,
          segmentField,
          pairwiseFeatures,
        },
        evidenceReferences,
      });
    },
    [
      activeCanonicalHandoff,
      dateField,
      datasetIdentity,
      documentationEvidence,
      findings,
      histogramBins,
      pairwiseFeatures,
      projectId,
      sections,
      segmentField,
    ],
  );

  useEffect(() => {
    if (
      !documentationHydrated ||
      confirmationPending ||
      !overview ||
      !datasetIdentity
    ) {
      return;
    }
    const payload = buildDocumentation();
    if (!payload) return;
    const approvedVersion =
      documentationState?.current_approved?.eda_analysis_version;
    if (
      documentationState?.status === "confirmed" &&
      approvedVersion === payload.eda_analysis_version
    ) {
      return;
    }
    if (
      lastDraftVersion.current === payload.eda_analysis_version &&
      documentationState?.draft?.eda_analysis_version ===
        payload.eda_analysis_version
    ) {
      return;
    }
    if (documentationDraftTimer.current !== null) {
      window.clearTimeout(documentationDraftTimer.current);
    }
    documentationDraftTimer.current = window.setTimeout(() => {
      setDocumentationMessage("Updating documentation draft…");
      void saveEdaDocumentationDraft(payload)
        .then((state) => {
          lastDraftVersion.current = payload.eda_analysis_version;
          setDocumentationState(state);
          setDocumentationMessage(
            state.status === "stale"
              ? "Draft changes saved. The approved documentation is now stale and requires reconfirmation."
              : "Documentation draft is synchronized with the current EDA state.",
          );
        })
        .catch((cause) => {
          setDocumentationMessage(
            cause instanceof Error
              ? cause.message
              : "ATLAS could not update the EDA documentation draft.",
          );
        });
    }, 700);
    return () => {
      if (documentationDraftTimer.current !== null) {
        window.clearTimeout(documentationDraftTimer.current);
        documentationDraftTimer.current = null;
      }
    };
  }, [
    buildDocumentation,
    confirmationPending,
    datasetIdentity,
    documentationHydrated,
    documentationState?.current_approved?.eda_analysis_version,
    documentationState?.draft?.eda_analysis_version,
    documentationState?.status,
    overview,
  ]);

  async function refreshActiveSection(overrides: Record<string, unknown> = {}) {
    await loadSection(activeTab, true, overrides);
  }

  async function saveEvidence(
    resolvedSections: Partial<Record<EDATab, WorkspaceResponse>> = sections,
  ): Promise<EdaDocumentationEvidenceReference | null> {
    const resolvedOverview = resolvedSections.overview;
    const findingsPayload = resolvedSections.findings;
    if (!resolvedOverview || !findingsPayload || !datasetIdentity) {
      setEvidenceMessage("Open the Findings tab before saving governed EDA evidence.");
      return null;
    }
    setEvidenceMessage("Saving evidence...");
    try {
      const governedFindings = buildGovernedFindingEvidencePayload(
        resolvedSections,
        findings,
      );
      const evidenceDocumentation = buildDocumentation(resolvedSections, []);
      if (!evidenceDocumentation) {
        throw new Error(
          "The governed EDA analysis identity is unavailable for durable evidence.",
        );
      }
      const evidenceId = [
        "eda-evidence",
        projectId,
        evidenceDocumentation.eda_analysis_version,
      ]
        .join("-")
        .replace(/[^A-Za-z0-9_.-]/g, "_");
      const evidence = await createEvidence({
        evidenceId,
        ...buildCanonicalEvidenceEnvelope(datasetIdentity, {
          target: resolvedOverview.target,
          predictorManifestId:
            resolvedOverview.predictor_authorization?.manifest_version,
          problemType: resolvedOverview.problem_type,
          eventValue: resolvedOverview.event_value,
          rowCount: resolvedOverview.row_count,
          scope: resolvedOverview.scope,
        }),
        projectName,
        evidenceType: "eda",
        title: "Governed Exploratory Data Analysis",
        summary: `Governed mixed-scope EDA for ${resolvedOverview.target}: target-directed metrics use the Development Population; structural diagnostics cover ${resolvedOverview.row_count.toLocaleString()} registered rows.`,
        sourcePage: "Exploratory Data Analysis",
        sourceRoute: "/step02",
        modelIds: [],
        documentIds: [],
        notebookIds: [],
        supportsSections: ["Exploratory Data Analysis", "Data Quality", "Feature Engineering"],
        tags: [
          "predictive_modeling",
          "eda",
          "development_target",
          "full_population_structure",
          "mixed_scope",
        ],
        status: isEdaOverallStatusEligible(findings.status)
          ? "ready"
          : "needs_review",
        importance: "high",
        artifactType: "governed_eda_analysis",
        artifactId: evidenceDocumentation.eda_analysis_version,
        sourceRunReference: evidenceDocumentation.eda_analysis_version,
        payload: {
          headline: resolvedOverview.headline,
          findings: governedFindings.parentFindings,
          childEvidence: governedFindings.childEvidence,
          sourceFindings: findingsPayload.findings,
          findingGroups: governedFindings.governance.finding_groups,
          carryForward: governedFindings.carryForward,
          automaticTransformationsApplied:
            governedFindings.automaticTransformationsApplied,
          userCommentary: findings.commentary,
          overallConclusion: findings.overallConclusion ?? "",
          findingStatus: findings.status,
          duplicateTreatment: findings.duplicateTreatment ?? "review",
          duplicateDecisionSavedAt: findings.duplicateDecisionSavedAt ?? null,
        },
      });
      const next = { ...findings, savedAt: new Date().toISOString() };
      if (findingsStorageKey) {
        localStorage.setItem(findingsStorageKey, JSON.stringify(next));
      }
      setFindings(next);
      setEvidenceMessage("EDA evidence saved.");
      const reference: EdaDocumentationEvidenceReference = {
        evidence_id: evidence.evidenceId,
        title: evidence.title,
        uri: `/evidence-graph?evidenceId=${encodeURIComponent(
          evidence.evidenceId,
        )}`,
        evidence_type: evidence.evidenceType,
      };
      setDocumentationEvidence([reference]);
      return reference;
    } catch (cause) {
      setEvidenceMessage(cause instanceof Error ? cause.message : "EDA evidence could not be saved.");
      return null;
    }
  }

  async function completeEDA(): Promise<boolean> {
    setConfirmationPending(true);
    setDocumentationMessage(
      "Validating the governed dataset, target, predictor manifest, findings, and documentation snapshot…",
    );
    try {
      if (!activeCanonicalHandoff || !activeHandoffKey) {
        throw new Error(
          "Confirmation is blocked until ATLAS verifies the exact current Data Acquisition handoff.",
        );
      }
      const resolvedSections: Partial<Record<EDATab, WorkspaceResponse>> = {
        ...sections,
      };
      for (const section of DOCUMENTATION_SECTIONS) {
        if (resolvedSections[section]) continue;
        const payload = await loadSection(section);
        if (payload) resolvedSections[section] = payload;
      }
      const missing = DOCUMENTATION_SECTIONS.filter(
        (section) => !resolvedSections[section],
      );
      if (missing.length) {
        throw new Error(
          `Confirmation is blocked until these governed EDA sections load successfully: ${missing.join(
            ", ",
          )}.`,
        );
      }
      if (!isEdaOverallStatusEligible(findings.status)) {
        throw new Error(
          "Choose an eligible overall EDA status: Accepted or Accepted with Conditions.",
        );
      }
      if (!String(findings.overallConclusion ?? "").trim()) {
        throw new Error(
          "Save the expert reviewer conclusion before confirming EDA.",
        );
      }
      if (!String(findings.commentary ?? "").trim()) {
        throw new Error(
          "Save reviewer commentary before confirming EDA.",
        );
      }
      const resolvedFindingsGovernance = summarizeFindingGovernance(
        generateEdaParentFindings(resolvedSections),
        findings,
      );
      const unresolvedRequiredParents =
        resolvedFindingsGovernance.unresolved_parent_finding_count;
      if (unresolvedRequiredParents > 0) {
        throw new Error(
          `${unresolvedRequiredParents} required parent finding${
            unresolvedRequiredParents === 1 ? " requires" : "s require"
          } an eligible governed disposition and rationale before confirming EDA.`,
        );
      }
      const resolvedOverview = resolvedSections.overview;
      const duplicateRows = Number(
        resolvedOverview?.headline?.duplicate_rows ?? 0,
      );
      const duplicateResolved =
        duplicateRows <= 0 ||
        ((findings.duplicateTreatment === "exclude" ||
          findings.duplicateTreatment === "keep") &&
          Boolean(findings.duplicateDecisionSavedAt));
      if (!duplicateResolved) {
        throw new Error(
          "Record and save a substantive duplicate-row treatment decision before confirming EDA.",
        );
      }

      let evidenceReferences = documentationEvidence;
      const candidate = buildDocumentation(
        resolvedSections,
        evidenceReferences,
      );
      if (!candidate) {
        throw new Error(
          "The registered dataset ID, version, target, or predictor manifest is unavailable. Reopen Data Acquisition and restore the governed dataset context.",
        );
      }
      const approvedMatches =
        documentationState?.status === "confirmed" &&
        documentationState.current_approved?.eda_analysis_version ===
          candidate.eda_analysis_version;
      if (!approvedMatches || evidenceReferences.length === 0) {
        const evidence = await saveEvidence(resolvedSections);
        if (!evidence) {
          throw new Error(
            "EDA evidence could not be created, so the documentation snapshot was not confirmed.",
          );
        }
        evidenceReferences = [evidence];
      }
      const confirmationPayload = buildDocumentation(
        resolvedSections,
        evidenceReferences,
      );
      if (!confirmationPayload) {
        throw new Error(
          "The governed EDA documentation payload could not be assembled.",
        );
      }
      if (confirmationPayload.unresolved_blocking_findings.length) {
        throw new Error(
          confirmationPayload.unresolved_blocking_findings.join(" "),
        );
      }

      const confirmation = await confirmEdaDocumentation(
        confirmationPayload,
      );
      if (!confirmation.next_step_eligible) {
        throw new Error(
          "The server persisted the EDA record but did not grant next-step eligibility.",
        );
      }
      if (!datasetIdentity) {
        throw new Error(
          "The exact registered Dataset Library version is unavailable.",
        );
      }
      const governedState = await getEdaDocumentationState(
        projectId,
        datasetIdentity,
      );
      setDocumentationState(governedState);
      setDocumentationEvidence(evidenceReferences);
      lastDraftVersion.current = "";
      setDocumentationMessage(
        `EDA confirmed as ${confirmation.documentation_version} (confirmation ${confirmation.confirmation_id}). Model Development Documentation is synchronized to the approved snapshot.`,
      );
      if (findingsStorageKey) {
        localStorage.setItem(findingsStorageKey, JSON.stringify(findings));
      }
      logDecision({
        workflowStep: "Exploratory Data Analysis",
        actionType: "workflow_setting_changed",
        subject: "EDA findings status",
        previousValue: "draft",
        newValue: findings.status,
        systemRecommendation:
          "Review governed findings and document any downstream treatment decisions.",
        userReason: findings.commentary,
      });
      return true;
    } catch (cause) {
      setDocumentationMessage(
        cause instanceof Error
          ? cause.message
          : "ATLAS could not confirm the governed EDA documentation snapshot.",
      );
      return false;
    } finally {
      setConfirmationPending(false);
    }
  }

  const activeData = activeCanonicalHandoff ? sections[activeTab] : undefined;
  const generatedParentFindingInventory = useMemo(
    () => generateEdaParentFindings(sections),
    [sections],
  );
  const findingsGovernance = useMemo(
    () => summarizeFindingGovernance(generatedParentFindingInventory, findings),
    [findings, generatedParentFindingInventory],
  );
  const unresolvedParentFindingCount =
    findingsGovernance.unresolved_parent_finding_count;
  const edaTabBadges = useMemo(
    () =>
      buildEdaTabBadges({
        loadedTabs: Object.keys(sections) as EDATab[],
        sectionPayloads: sections,
        unresolvedParentFindings: unresolvedParentFindingCount,
        governedFieldAvailabilityKnown: Boolean(overview),
        hasGovernedTimeFields:
          safeArray(available.date_candidates).length > 0,
        hasGovernedSegmentFields:
          safeArray(available.segment_candidates).length > 0,
      }),
    [
      available.date_candidates,
      available.segment_candidates,
      overview,
      sections,
      unresolvedParentFindingCount,
    ],
  );
  const duplicateRows = Number(overview?.headline?.duplicate_rows ?? 0);
  const duplicateDecisionComplete =
    duplicateRows <= 0 ||
    ((findings.duplicateTreatment === "exclude" ||
      findings.duplicateTreatment === "keep") &&
      Boolean(findings.duplicateDecisionSavedAt));
  const reviewerConclusionComplete = Boolean(
    String(findings.overallConclusion ?? "").trim(),
  );
  const reviewerCommentaryComplete = Boolean(
    String(findings.commentary ?? "").trim(),
  );
  const overallStatusEligible = isEdaOverallStatusEligible(findings.status);
  const locallyReady =
    Boolean(overview) &&
    overallStatusEligible &&
    unresolvedParentFindingCount === 0 &&
    reviewerConclusionComplete &&
    reviewerCommentaryComplete &&
    duplicateDecisionComplete;
  const confirmationStatus = confirmationPending
    ? "Confirming…"
    : documentationState?.status === "confirmed"
      ? "Confirmed"
      : documentationState?.status === "stale"
        ? "Stale after upstream change"
        : documentationState?.status === "ready_for_confirmation" ||
            locallyReady
          ? "Ready for confirmation"
          : "Draft";
  const confirmationState = confirmationPending
    ? "confirming"
    : documentationState?.status === "confirmed"
      ? "confirmed"
      : documentationState?.status === "stale"
        ? "stale"
        : confirmationStatus === "Ready for confirmation"
          ? "ready"
          : "draft";
  const nextDisabled =
    !activeCanonicalHandoff ||
    handoffLoading ||
    !overview ||
    Boolean(loading) ||
    confirmationPending ||
    Boolean(error) ||
    unresolvedParentFindingCount > 0 ||
    !reviewerConclusionComplete ||
    !reviewerCommentaryComplete ||
    !overallStatusEligible ||
    !duplicateDecisionComplete;
  const completionBlockers = useMemo<EdaCompletionBlocker[]>(() => {
    const blockers: EdaCompletionBlocker[] = [];
    if (!datasetIdentity) {
      blockers.push({
        id: "canonical-identity",
        message: "Restore the exact registered dataset identity in Data Acquisition.",
      });
    }
    if (!activeCanonicalHandoff) {
      blockers.push({
        id: "canonical-handoff",
        message: handoffLoading
          ? "Wait for the exact Data Acquisition handoff to be verified."
          : "Revalidate the exact Data Acquisition handoff before continuing.",
      });
    }
    if (!overview) {
      blockers.push({
        id: "overview",
        message: "Load the governed EDA overview.",
        destination: "overview",
      });
    }
    if (error) {
      blockers.push({
        id: "analysis-error",
        message: `${
          tabs.find((tab) => tab.id === activeTab)?.label ?? "EDA"
        } analysis is unavailable; retry the governed request.`,
        destination: activeTab,
      });
    }
    if (loading) {
      blockers.push({
        id: "analysis-loading",
        message: `Wait for ${tabs.find((tab) => tab.id === loading)?.label ?? "EDA"} analysis to finish.`,
        destination: loading,
      });
    }
    if (unresolvedParentFindingCount > 0) {
      blockers.push({
        id: "required-parent-findings",
        message: `${unresolvedParentFindingCount} parent finding${
          unresolvedParentFindingCount === 1 ? " requires" : "s require"
        } a governed disposition and rationale.`,
        destination: "findings",
      });
    }
    if (!duplicateDecisionComplete) {
      blockers.push({
        id: "duplicate-treatment",
        message: "Save the duplicate-row treatment decision.",
        destination: "findings",
      });
    }
    if (!reviewerConclusionComplete) {
      blockers.push({
        id: "reviewer-conclusion",
        message: "Save the expert reviewer conclusion.",
        destination: "findings",
      });
    }
    if (!reviewerCommentaryComplete) {
      blockers.push({
        id: "reviewer-commentary",
        message: "Save reviewer commentary.",
        destination: "findings",
      });
    }
    if (!overallStatusEligible) {
      blockers.push({
        id: "overall-status",
        message: "Choose Accepted or Accepted with Conditions as the overall EDA status.",
        destination: "findings",
      });
    }
    return blockers;
  }, [
    activeTab,
    activeCanonicalHandoff,
    datasetIdentity,
    duplicateDecisionComplete,
    error,
    loading,
    handoffLoading,
    overallStatusEligible,
    overview,
    reviewerCommentaryComplete,
    reviewerConclusionComplete,
    unresolvedParentFindingCount,
  ]);
  const completionSummary = useMemo(
    () => summarizeEdaCompletionBlockers(completionBlockers),
    [completionBlockers],
  );
  const nextDisabledReason = nextDisabled
    ? completionSummary.text
    : undefined;
  const documentationImpact = documentationImpactByTab[activeTab];
  const predictorAuthorization = safeObject(overview?.predictor_authorization);
  const rawAuthorizedPredictors =
    predictorAuthorization.authorized_predictors;
  const authorizedPredictors = safeArray<string>(
    rawAuthorizedPredictors,
  );
  const targetSourceExclusions = safeArray<string>(
    overview?.target_source_excluded ??
      predictorAuthorization.target_source_excluded,
  );
  const datasetDisplayName = String(
    activeCanonicalHandoff?.context.identity.dataset_name ||
      datasetIdentity?.dataset_id ||
      projectName ||
      "Registered dataset",
  );
  const datasetVersionLabel = String(
    datasetIdentity?.dataset_version_label ??
      datasetIdentity?.dataset_version_id ??
      "Version pending",
  );
  const predictorManifestState: "loading" | "verified" | "unverified" =
    !activeCanonicalHandoff || (!overview && loading === "overview")
      ? "loading"
      : overview &&
          Array.isArray(rawAuthorizedPredictors) &&
          String(
            predictorAuthorization.predictor_authorization_id ??
              predictorAuthorization.manifest_version ??
              "",
          ).trim() ===
            activeCanonicalHandoff.context.predictor_authorization
              .predictor_authorization_id
        ? "verified"
        : "unverified";
  const predictorManifestLabel =
    predictorManifestState === "loading"
      ? "Checking manifest..."
      : predictorManifestState === "verified"
        ? activeCanonicalHandoff?.context.predictor_authorization
            .predictor_authorization_id ?? "Not verified"
        : "Manifest not verified";
  const headlinePredictorCount = Number(overview?.headline?.predictors);
  const predictorCount =
    predictorManifestState === "verified"
      ? Number.isFinite(headlinePredictorCount)
        ? Math.max(0, headlinePredictorCount)
        : authorizedPredictors.length
      : null;
  const activeTabLabel =
    tabs.find((tab) => tab.id === activeTab)?.label ?? titleCase(activeTab);
  const activateEdaTab = useCallback(
    (tab: EDATab, focus = false) => {
      setActiveTab(tab);
      if (!focus) return;
      window.requestAnimationFrame(() => tabRefs.current[tab]?.focus());
    },
    [],
  );
  const handleEdaTabKeyDown = useCallback(
    (event: React.KeyboardEvent<HTMLButtonElement>, tab: EDATab) => {
      const nextTab = tabForKeyboardNavigation(tab, event.key);
      if (!nextTab) return;
      event.preventDefault();
      activateEdaTab(nextTab, true);
    },
    [activateEdaTab],
  );
  const goToEdaRequirement = useCallback(
    (tab: EDATab) => {
      activateEdaTab(tab, true);
      window.requestAnimationFrame(() => {
        firstAnalyticalContentRef.current?.scrollIntoView({
          block: "start",
          behavior: "smooth",
        });
      });
    },
    [activateEdaTab],
  );
  const analysisState = loading
    ? `Running ${activeTabLabel}`
    : error
      ? "Analysis unavailable"
      : overview
        ? "Analysis available"
        : "Connecting to governed data";
  const documentationMessageIsBlocking =
    Boolean(documentationMessage) &&
    (confirmationState === "stale" ||
      /could not|cannot|failed|blocked|unavailable|requires? reconfirmation|missing|invalid|error/i.test(
        documentationMessage,
      ));
  const documentationBlockerMessage =
    confirmationState === "stale"
      ? documentationMessage ||
        "The approved EDA documentation is stale after an upstream change and must be reconfirmed."
      : documentationMessageIsBlocking
        ? documentationMessage
        : "";
  const activeBlockerMessage = error
    ? `The ${activeTabLabel} analysis is unavailable: ${error.message}`
    : documentationBlockerMessage
      ? documentationBlockerMessage
      : !loading && nextDisabled && nextDisabledReason
        ? nextDisabledReason
        : "";
  const activeBlockerSource = error
    ? "analysis"
    : documentationBlockerMessage
      ? "documentation"
      : activeBlockerMessage
        ? "workflow"
        : "none";
  const analysisPartitionBlocker =
    error?.domain === "analysis_partition" ? error : null;

  const quickSummaryItems = useMemo<EdaQuickSummaryItem[]>(() => {
    const overviewHeadline = safeObject(overview?.headline);
    const overviewIntegrity = safeObject(overview?.data_integrity);
    const active = activeData ?? overview;

    if (activeTab === "overview") {
      const constantCount = safeArray(
        overviewIntegrity.constant_columns,
      ).length;
      const leakageCount = safeArray(
        overviewIntegrity.leakage_candidates,
      ).length;
      const missingCells = Number(overviewHeadline.missing_cells ?? 0);
      const duplicateCount = Number(overviewHeadline.duplicate_rows ?? 0);
      const readinessChecks = [
        missingCells === 0,
        duplicateCount === 0,
        constantCount === 0,
        leakageCount === 0,
      ];
      const cleared = readinessChecks.filter(Boolean).length;
      const mainReviewItem =
        duplicateCount > 0
          ? `${formatNumber(duplicateCount, 0)} duplicate rows`
          : missingCells > 0
            ? `${formatNumber(missingCells, 0)} missing cells`
            : leakageCount > 0
              ? `${formatNumber(leakageCount, 0)} leakage-name candidates`
              : constantCount > 0
                ? `${formatNumber(constantCount, 0)} constant predictors`
                : "No headline escalation";
      const targetProfile = safeObject(overview?.target_profile);
      const targetBalance =
        overview?.problem_type === "classification"
          ? formatPercent(targetProfile.event_rate)
          : formatNumber(targetProfile.mean);
      return [
        {
          label: "Population",
          value: formatNumber(
            overviewHeadline.rows ?? overview?.row_count,
            0,
          ),
        },
        {
          label: "Predictors",
          value: formatNumber(overviewHeadline.predictors, 0),
        },
        {
          label: "Target balance",
          value: targetBalance,
          tone: "info",
        },
        {
          label: "Readiness",
          value:
            cleared === readinessChecks.length
              ? "Checks clear"
              : `${cleared}/${readinessChecks.length} checks clear`,
          tone:
            cleared === readinessChecks.length ? "success" : "warning",
        },
        {
          label: "Main review item",
          value: mainReviewItem,
          tone:
            mainReviewItem === "No headline escalation"
              ? "success"
              : "warning",
        },
      ];
    }

    if (activeTab === "target") {
      const profile = safeObject(
        active?.profile ?? overview?.target_profile,
      );
      const identity = safeObject(active?.identity);
      const targetQuality = safeObject(active?.target_quality);
      const source =
        identity.source ??
        targetSourceExclusions[0] ??
        "governed source";
      const unexpectedCount = safeArray(profile.unexpected_values).length;
      const missingCount = Number(profile.missing_count ?? 0);
      const quality =
        missingCount === 0 && unexpectedCount === 0
          ? "Checks clear"
          : `${formatNumber(missingCount, 0)} missing · ${formatNumber(
              unexpectedCount,
              0,
            )} unexpected`;
      return [
        {
          label: "Target lineage",
          value: `${overview?.target ?? active?.target ?? "Target"} <- ${String(
            source,
          )}`,
        },
        {
          label: "Prevalence",
          value:
            (active?.problem_type ?? overview?.problem_type) ===
            "classification"
              ? formatPercent(profile.event_rate)
              : formatNumber(profile.mean),
          tone: "info",
        },
        {
          label: "Class balance",
          value:
            profile.event_count !== undefined
              ? `${formatNumber(profile.event_count, 0)} event / ${formatNumber(
                  profile.non_event_count,
                  0,
                )} non-event`
              : "Regression target",
        },
        {
          label: "Quality",
          value:
            String(targetQuality.status ?? "").trim() || quality,
          tone: quality === "Checks clear" ? "success" : "warning",
        },
      ];
    }

    if (activeTab === "predictors") {
      const predictorRows = [
        ...safeArray<any>(active?.numeric),
        ...safeArray<any>(active?.categorical),
      ];
      const signalKey =
        (active?.problem_type ?? overview?.problem_type) ===
        "classification"
          ? "iv"
          : "correlation_with_target";
      const strongest =
        [...predictorRows].sort(
          (left, right) =>
            Math.abs(Number(right?.[signalKey] ?? 0)) -
            Math.abs(Number(left?.[signalKey] ?? 0)),
        )[0] ?? null;
      const selected =
        predictorRows.find(
          (row) => String(row.feature) === selectedVariable,
        ) ??
        strongest ??
        null;
      const signalLabel = signalKey === "iv" ? "IV" : "Correlation";
      return [
        {
          label: "Selected predictor",
          value: String(selected?.feature ?? "Awaiting analysis"),
        },
        {
          label: signalLabel,
          value: formatNumber(selected?.[signalKey], 3),
          tone: "info",
        },
        {
          label: "Missingness",
          value: formatPercent(selected?.missing_rate),
        },
        {
          label: "Monotonicity",
          value: String(selected?.monotonicity ?? "Not evaluated"),
        },
        {
          label: "Strongest pattern",
          value: strongest
            ? `${String(strongest.feature)} · ${signalLabel} ${formatNumber(
                strongest[signalKey],
                3,
              )}`
            : "Awaiting analysis",
          tone: strongest ? "success" : "neutral",
        },
      ];
    }

    if (activeTab === "relationships") {
      const strongPairs = safeArray<any>(active?.strong_pairs);
      const strongestPair = strongPairs[0];
      const vifRows = safeArray<any>(active?.vif);
      const highestVif = vifRows[0];
      const vifReviewCount = vifRows.filter(
        (row) =>
          row.is_infinite ||
          row.status === "review" ||
          row.status === "high" ||
          Number(row.vif) >= 5,
      ).length;
      const selectedPair = pinnedPair
        ? `${pinnedPair.a} × ${pinnedPair.b}`
        : relationshipAxes.x && relationshipAxes.y
          ? `${relationshipAxes.x} × ${relationshipAxes.y}`
          : "None pinned";
      return [
        {
          label: "Strongest pair",
          value: strongestPair
            ? `${String(strongestPair.feature_a)} × ${String(
                strongestPair.feature_b,
              )} · ${formatNumber(strongestPair.correlation, 2)}`
            : "No pair above threshold",
          tone: strongestPair ? "warning" : "success",
        },
        {
          label: "Max VIF",
          value: highestVif?.is_infinite
            ? "Infinite"
            : formatNumber(highestVif?.vif, 2),
          tone:
            highestVif?.status === "high" || highestVif?.is_infinite
              ? "danger"
              : highestVif?.status === "review"
                ? "warning"
                : "success",
        },
        {
          label: "Review count",
          value: formatNumber(vifReviewCount, 0),
          tone: vifReviewCount ? "warning" : "success",
        },
        { label: "Selected pair", value: selectedPair },
      ];
    }

    if (activeTab === "stability") {
      const timeRows = safeArray(active?.time_profile);
      const segmentRows = safeArray(active?.segment_profile);
      const timeCandidates = safeArray(available.date_candidates);
      const segmentCandidates = safeArray(
        available.segment_candidates,
      );
      const availableAnalyses = [
        timeRows.length ? "Time" : null,
        segmentRows.length ? "Segments" : null,
      ].filter(Boolean);
      return [
        {
          label: "Time fields",
          value: formatNumber(timeCandidates.length, 0),
        },
        {
          label: "Time periods",
          value: formatNumber(timeRows.length, 0),
        },
        {
          label: "Segment fields",
          value: formatNumber(segmentCandidates.length, 0),
        },
        {
          label: "Segments",
          value: formatNumber(segmentRows.length, 0),
        },
        {
          label: "Availability",
          value: availableAnalyses.length
            ? availableAnalyses.join(" + ")
            : timeCandidates.length || segmentCandidates.length
              ? "Ready to configure"
              : "No governed fields",
          tone: availableAnalyses.length ? "success" : "warning",
        },
      ];
    }

    const findingRows = safeArray<any>(active?.findings);
    const findingBlockers = findingRows.filter((row) =>
      /warning|danger|critical|block/i.test(
        String(row.severity ?? row.status ?? ""),
      ),
    ).length;
    const workflowBlockers =
      findingBlockers +
      (duplicateDecisionComplete ? 0 : 1) +
      (confirmationState === "stale" ? 1 : 0);
    return [
      {
        label: "Open",
        value: formatNumber(unresolvedParentFindingCount, 0),
      },
      {
        label: "Accepted",
        value: isEdaOverallStatusEligible(findings.status) ? "Yes" : "No",
        tone: isEdaOverallStatusEligible(findings.status)
          ? "success"
          : "warning",
      },
      {
        label: "Blockers",
        value: formatNumber(workflowBlockers, 0),
        tone: workflowBlockers ? "danger" : "success",
      },
      {
        label: "Documentation state",
        value: confirmationStatus,
        tone:
          confirmationState === "confirmed"
            ? "success"
            : confirmationState === "stale"
              ? "danger"
              : "info",
      },
      {
        label: "Evidence",
        value: formatNumber(documentationEvidence.length, 0),
      },
    ];
  }, [
    activeData,
    activeTab,
    available.date_candidates,
    available.segment_candidates,
    confirmationState,
    confirmationStatus,
    documentationEvidence.length,
    duplicateDecisionComplete,
    findings.status,
    overview,
    pinnedPair,
    relationshipAxes.x,
    relationshipAxes.y,
    selectedVariable,
    targetSourceExclusions,
    unresolvedParentFindingCount,
  ]);

  useEffect(() => {
    const element = compactPreambleRef.current;
    if (!element) return;
    const breadcrumb = document.querySelector<HTMLElement>(
      '[data-testid="atlas-breadcrumb"]',
    );
    const appHeader = breadcrumb?.closest<HTMLElement>("header") ?? null;
    let frame = 0;
    const measure = () => {
      const nextHeight = Math.round(
        element.getBoundingClientRect().height,
      );
      setCompactPreambleHeight((current) =>
        current === nextHeight ? current : nextHeight,
      );
      if (appHeader) {
        const nextStickyTop =
          Math.ceil(appHeader.getBoundingClientRect().height) + 8;
        setStickyTopOffset((current) =>
          current === nextStickyTop ? current : nextStickyTop,
        );
      }
    };
    const scheduleMeasure = () => {
      window.cancelAnimationFrame(frame);
      frame = window.requestAnimationFrame(measure);
    };
    scheduleMeasure();
    window.addEventListener("resize", scheduleMeasure);
    if (typeof ResizeObserver === "undefined") {
      return () => {
        window.cancelAnimationFrame(frame);
        window.removeEventListener("resize", scheduleMeasure);
      };
    }
    const observer = new ResizeObserver(scheduleMeasure);
    observer.observe(element);
    if (appHeader) observer.observe(appHeader);
    return () => {
      observer.disconnect();
      window.cancelAnimationFrame(frame);
      window.removeEventListener("resize", scheduleMeasure);
    };
  }, []);

  return (
    <StepShell
      title="Step 2: Exploratory Data Analysis"
      subtitle="Examine the full modeling population, target behavior, predictor quality, relationships, stability, segments, and governed findings before treatment decisions."
      hideHeader
      nextPath={getNextStepPath("step02")}
      nextDisabled={nextDisabled}
      nextDisabledReason={nextDisabledReason}
      nextLabel="Confirm EDA and Continue"
      onNext={completeEDA}
      nextAlwaysVisible
      nextFooterTestId="eda-completion-bar"
      nextStatusTestId="eda-completion-summary"
      nextStatusLine={
        analysisPartitionBlocker
          ? "Analysis Partition required. Return to Data Acquisition to confirm the governed development and sealed holdout assignment."
          : completionSummary.text
      }
      nextExtraActions={
        analysisPartitionBlocker ? (
          <Link
            className="atlas-secondary-button"
            to={projectWorkflowRoute(projectId, "/step01#analysis-partition-readiness")}
            data-testid="eda-analysis-partition-footer-action"
          >
            Return to Data Acquisition
          </Link>
        ) : completionSummary.destination ? (
          <button
            type="button"
            className="atlas-secondary-button"
            data-testid="eda-completion-direct-action"
            onClick={() => goToEdaRequirement(completionSummary.destination!)}
          >
            Go to {tabs.find((tab) => tab.id === completionSummary.destination)?.label}
          </button>
        ) : undefined
      }
    >
      {analysisPartitionBlocker ? (
        <AnalysisPartitionRequiredShell
          error={analysisPartitionBlocker}
          projectId={projectId}
          onRetry={() => void loadSection("overview", true)}
        />
      ) : (
      <div className="eda-premium-page">
        <div
          ref={compactPreambleRef}
          className="eda-compact-preamble"
          data-testid="eda-compact-preamble"
          data-preamble-target-px="380"
          data-measured-preamble-px={
            compactPreambleHeight ?? "pending"
          }
          data-preamble-budget-status={
            compactPreambleHeight === null
              ? "pending"
              : compactPreambleHeight <= 380
                ? "within-budget"
                : "over-budget"
          }
        >
          <header
            className="eda-compact-page-header"
            data-testid="eda-compact-page-header"
            data-page-identity="exploratory-data-analysis"
          >
            <div className="eda-compact-title-lockup">
              <span className="eda-compact-title-mark" aria-hidden="true">
                <BarChart3 size={18} />
              </span>
              <div className="min-w-0">
                <div className="eda-compact-eyebrow">
                  EDA intelligence workspace · Step 2
                </div>
                <h1>Step 2: Exploratory Data Analysis</h1>
                <p>
                  Governed population, target, predictor, relationship,
                  stability, and reviewer evidence.
                </p>
              </div>
            </div>
            <span
              className="eda-compact-current-view sr-only"
              aria-label={`Current EDA view: ${activeTabLabel}`}
            >
              Current EDA view: {activeTabLabel}
            </span>
          </header>

          <div
            className="eda-compact-sticky"
            data-testid="eda-compact-navigation"
            data-global-header-offset-px={stickyTopOffset}
            style={
              {
                "--eda-sticky-top": `${stickyTopOffset}px`,
              } as React.CSSProperties
            }
          >
            <section
              className="eda-governed-context-strip"
              aria-label="Governed EDA context"
              data-testid="eda-governed-context-strip"
              data-context-panel="governed"
              data-active-tab={activeTab}
            >
              <div
                className="eda-governed-context-content"
                data-testid="eda-predictor-authorization"
              >
              <div
                className="eda-context-item eda-context-item--dataset"
                title={`${datasetDisplayName} · ${datasetIdentity?.dataset_id ?? "Pending"} · ${datasetVersionLabel}`}
              >
                <Database size={14} aria-hidden="true" />
                <span>
                  <small>Dataset / version</small>
                  <strong>
                    {datasetIdentity?.dataset_id ?? "Pending"} · {datasetVersionLabel}
                  </strong>
                </span>
              </div>
              <div className="eda-context-item">
                <Target size={14} aria-hidden="true" />
                <span>
                  <small>Target</small>
                  <strong>
                    {activeCanonicalHandoff
                      ? `${activeCanonicalHandoff.context.target_contract.target} · ${String(activeCanonicalHandoff.context.target_contract.event_value)} / ${String(activeCanonicalHandoff.context.target_contract.non_event_value)}`
                      : "Pending"}
                  </strong>
                </span>
              </div>
              <div className="eda-context-item">
                <Layers3 size={14} aria-hidden="true" />
                <span>
                  <small>Predictor manifest</small>
                  {predictorCount === null ? (
                    <strong data-manifest-state={predictorManifestState}>
                      {predictorManifestLabel}
                    </strong>
                  ) : (
                  <strong>
                    {predictorCount.toLocaleString()} ·{" "}
                    {predictorManifestLabel}
                  </strong>
                  )}
                </span>
              </div>
              <div className="eda-context-item" data-testid="eda-analysis-partition-identity">
                <ShieldCheck size={14} aria-hidden="true" />
                <span>
                  <small>Analysis Partition</small>
                  <strong>
                    {activeCanonicalHandoff
                      ? `${activeCanonicalHandoff.context.analysis_partition.analysis_partition_id} · r${activeCanonicalHandoff.context.analysis_partition.revision}`
                      : "Pending"}
                  </strong>
                </span>
              </div>
              <div
                className="eda-context-item eda-context-item--documentation"
                data-testid="eda-documentation-impact"
                title={documentationImpact.detail}
              >
                <FileText size={14} aria-hidden="true" />
                <span>
                  <small>Documentation impact</small>
                  <strong>{documentationImpact.title}</strong>
                </span>
              </div>
              <div
                className={`eda-context-state eda-context-state--${confirmationState}`}
                data-testid="eda-confirmation-status"
                data-confirmation-state={confirmationState}
              >
                {confirmationState === "confirmed" ||
                confirmationState === "ready" ? (
                  <CheckCircle2 size={13} aria-hidden="true" />
                ) : (
                  <CircleAlert size={13} aria-hidden="true" />
                )}
                <span>{confirmationStatus}</span>
              </div>
              <div
                className={`eda-context-state ${
                  error
                    ? "eda-context-state--stale"
                    : overview
                      ? "eda-context-state--confirmed"
                      : "eda-context-state--draft"
                }`}
              >
                <Activity size={13} aria-hidden="true" />
                <span>{analysisState}</span>
              </div>
              <div className="eda-backend-enforced">
                <ShieldCheck size={13} aria-hidden="true" />
                Backend enforced
              </div>
              <details
                className="eda-context-details"
                data-testid="eda-governed-context-details"
              >
                <summary>Details</summary>
                <div className="eda-context-details-panel">
                  <div>
                    <div className="eda-detail-label">
                      Current tab documentation
                    </div>
                    <div className="eda-detail-title">
                      {documentationImpact.title}
                    </div>
                    <p>{documentationImpact.detail}</p>
                  </div>
                  <div>
                    <div className="eda-detail-label">
                      Dataset lineage
                    </div>
                    <dl>
                      <div>
                        <dt>Dataset</dt>
                        <dd>{datasetDisplayName}</dd>
                      </div>
                      <div>
                        <dt>Dataset ID</dt>
                        <dd>
                          {datasetIdentity?.dataset_id ??
                            "Not available"}
                        </dd>
                      </div>
                      <div>
                        <dt>Version</dt>
                        <dd>{datasetVersionLabel}</dd>
                      </div>
                      <div>
                        <dt>Target</dt>
                        <dd>
                          {overview?.target ??
                            activeCanonicalHandoff?.context.target_contract.target ??
                            "Pending"}
                        </dd>
                      </div>
                    </dl>
                  </div>
                  <div>
                    <div className="eda-detail-label">
                      Server-authorized predictor manifest
                    </div>
                    {predictorManifestState === "verified" ? (
                      <p>
                        {authorizedPredictors.length.toLocaleString()} eligible predictors under{" "}
                        {predictorManifestLabel}. The modeling target
                        {targetSourceExclusions.length
                          ? ` and deterministic target source ${targetSourceExclusions.join(
                              ", ",
                            )}`
                          : ""}{" "}
                        are excluded from every governed visual.
                      </p>
                    ) : (
                      <p>
                        {predictorManifestLabel}. ATLAS will not present an absent
                        or failed server manifest as zero authorized predictors.
                      </p>
                    )}
                    {predictorManifestState === "verified" && authorizedPredictors.length ? (
                      <p>
                        <strong>Authorized fields:</strong>{" "}
                        {authorizedPredictors.join(", ")}
                      </p>
                    ) : null}
                  </div>
                  <div>
                    <div className="eda-detail-label">
                      Documentation state
                    </div>
                    <p>
                      {confirmationStatus}.{" "}
                      {documentationMessage ||
                        "No documentation synchronization message is active."}
                    </p>
                  </div>
                </div>
              </details>
              <span className="sr-only">
                Server-authorized predictor manifest.{" "}
                {targetSourceExclusions.join(", ")}. Backend
                enforced.
              </span>
              </div>
            </section>

            <nav
              className="eda-tab-rail p-1.5"
              aria-label="EDA analysis navigation"
              data-testid="eda-analysis-tab-rail"
              data-active-tab={activeTab}
            >
          <div className="flex flex-col gap-2 xl:flex-row xl:items-center xl:justify-between">
            <div className="flex min-w-0 gap-1 overflow-x-auto" role="tablist" aria-label="EDA analysis sections">
              {tabs.map((tab) => {
                const Icon = tab.icon;
                const selected = activeTab === tab.id;
                const badge = edaTabBadges[tab.id];
                return (
                  <button
                    key={tab.id}
                    ref={(element) => {
                      tabRefs.current[tab.id] = element;
                    }}
                    type="button"
                    role="tab"
                    id={`eda-tab-${tab.id}`}
                    aria-controls={`eda-tabpanel-${tab.id}`}
                    aria-selected={selected}
                    tabIndex={selected ? 0 : -1}
                    data-tab-id={tab.id}
                    data-tab-status={badge.kind}
                    className={[
                      "atlas-tab-button shrink-0 gap-2 border",
                      selected
                        ? "atlas-tab-button-active border-blue-600"
                        : "atlas-tab-button-inactive border-slate-200 bg-white shadow-sm",
                    ].join(" ")}
                    onClick={() => activateEdaTab(tab.id)}
                    onKeyDown={(event) => handleEdaTabKeyDown(event, tab.id)}
                  >
                    <Icon size={16} aria-hidden="true" />
                    <span>{tab.label}</span>
                    <span
                      className={`eda-tab-status eda-tab-status--${badge.kind}`}
                      data-testid={`eda-tab-status-${tab.id}`}
                      aria-label={`${tab.label}: ${badge.label}`}
                    >
                      {badge.label}
                    </span>
                  </button>
                );
              })}
            </div>
            <div className="flex shrink-0 items-center gap-2 px-2">
              {selectedVariable ? (
                <div
                  className="flex max-w-[430px] items-center gap-2 rounded-lg border border-blue-200 bg-blue-50 px-2.5 py-1.5 text-[11px] text-blue-950"
                  data-testid="eda-linked-selection-summary"
                >
                  <span className="font-semibold">{selectedVariable}</span>
                  {selectedRange?.feature === selectedVariable ? (
                    <span className="truncate tabular-nums">
                      {formatNumber(selectedRange.min, 3)} to {formatNumber(selectedRange.max, 3)}
                    </span>
                  ) : null}
                  {pinnedPair ? <span className="truncate">{pinnedPair.a} × {pinnedPair.b}</span> : null}
                  {relationshipAxes.z ? (
                    <span className="truncate">Z: {relationshipAxes.z}</span>
                  ) : null}
                  {(selectedRange ||
                  pinnedPair ||
                  relationshipAxes.x ||
                  relationshipAxes.y ||
                  relationshipAxes.z) ? (
                    <button type="button" className="font-semibold underline" onClick={clearVisualSelection}>
                      Clear selection
                    </button>
                  ) : null}
                </div>
              ) : null}
              {activeData ? <AtlasDataScopeBadge scope={activeData.scope} rows={activeData.row_count} /> : null}
              <button type="button" className="atlas-secondary-button" onClick={() => void refreshActiveSection()} disabled={!!loading}>
                <RefreshCw size={15} className={loading === activeTab ? "animate-spin" : ""} />
                Refresh
              </button>
            </div>
          </div>
        </nav>
          </div>

          <EdaTabQuickSummary
            activeTab={activeTab}
            activeTabLabel={activeTabLabel}
            items={quickSummaryItems}
          />

          {activeBlockerMessage ? (
          <div
              className="eda-active-context-blocker"
              role="alert"
            aria-live="polite"
            aria-atomic="true"
              data-testid="eda-active-context-blocker"
              data-blocker-source={activeBlockerSource}
          >
              <AlertTriangle size={15} aria-hidden="true" />
              <span>
                <strong>Active blocker:</strong>{" "}
                <span
                  data-testid={
                    activeBlockerSource === "documentation"
                      ? "eda-documentation-message"
                      : undefined
                  }
                >
                  {activeBlockerMessage}
                </span>
              </span>
          </div>
        ) : null}
          {documentationMessage &&
          !documentationBlockerMessage ? (
            <span
              className="sr-only"
              role="status"
              aria-live="polite"
              aria-atomic="true"
              data-testid="eda-documentation-message"
            >
              {documentationMessage}
            </span>
          ) : null}
        </div>

        {datasetIdentity && activeCanonicalHandoff ? (
          <BureauSemanticContextPanel
            datasetIdentity={datasetIdentity}
            datasetFields={
              activeCanonicalHandoff.context.predictor_authorization
                .authorized_predictors
            }
            pageName="EDA"
          />
        ) : null}

        <div
          ref={firstAnalyticalContentRef}
          id={`eda-tabpanel-${activeTab}`}
          role="tabpanel"
          aria-labelledby={`eda-tab-${activeTab}`}
          tabIndex={0}
          data-testid="eda-first-analytical-content"
          data-active-tab={activeTab}
          data-preamble-target-px="380"
          data-measured-preamble-px={
            compactPreambleHeight ?? "pending"
          }
        >
          <div key={activeTab} className="eda-tab-stage space-y-4">
          {error ? (
            <EDAUnavailablePanel
              error={error}
              projectId={projectId}
              onRetry={() => void refreshActiveSection()}
            />
          ) : null}

          {(handoffLoading || loading === activeTab) && !activeData ? (
            <LoadingPanel
              label={
                handoffLoading
                  ? "Verifying the exact Data Acquisition contract"
                  : `Running ${tabs.find((tab) => tab.id === activeTab)?.label} analysis`
              }
            />
          ) : null}

          {activeTab === "overview" && overview ? <OverviewPanel data={overview} /> : null}
          {!handoffLoading && !loading && !error && !activeData ? (
            <AtlasAttentionPanel title="EDA section not loaded" tone="info">
              This section has not returned profile data yet. Use Refresh to retry the governed backend request.
            </AtlasAttentionPanel>
          ) : null}
          {activeTab === "target" && activeData && activeCanonicalHandoff ? (
            <TargetIntelligenceWorkspace
              data={activeData}
              projectId={projectId}
              projectName={projectName}
              datasetIdentity={
                datasetIdentity
                  ? {
                      datasetId: datasetIdentity.dataset_id,
                      versionId: datasetIdentity.dataset_version_id,
                      datasetName:
                        activeCanonicalHandoff?.context.identity.dataset_name ?? "",
                    }
                  : null
              }
              eventValue={
                activeData.event_value ??
                activeCanonicalHandoff?.context.target_contract.event_value
              }
              nonEventValue={
                activeCanonicalHandoff?.context.target_contract.non_event_value
              }
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
              canonicalHandoff={activeCanonicalHandoff}
            />
          ) : null}
          {activeTab === "predictors" && activeData && activeCanonicalHandoff ? (
            <PredictorsPanel
              data={activeData}
              histogramBins={histogramBins}
              onHistogramBins={setHistogramBins}
              projectId={projectId}
              canonicalRequest={canonicalRequestContract ?? {}}
              canonicalHandoff={activeCanonicalHandoff}
            />
          ) : null}
          {activeTab === "relationships" && activeData && activeCanonicalHandoff ? (
            <RelationshipsPanel
              data={activeData}
              numericFields={available.numeric ?? []}
              segmentFields={available.segment_candidates ?? []}
              pairwiseFeatures={pairwiseFeatures}
              onPairwiseFeatures={setPairwiseFeatures}
              projectId={projectId}
              canonicalRequest={canonicalRequestContract ?? {}}
              canonicalHandoff={activeCanonicalHandoff}
              onRun={(overrides) => void refreshActiveSection(overrides)}
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
            <FindingsDecisionWorkspace
              sections={{ ...sections, findings: activeData }}
              state={findings}
              onChange={(next) => {
                setFindings(next);
                if (findingsStorageKey) {
                  localStorage.setItem(
                    findingsStorageKey,
                    JSON.stringify(next),
                  );
                }
              }}
              onSave={() => void saveEvidence()}
              message={evidenceMessage}
              documentationStatus={documentationState?.status}
              data-testid="eda-duplicate-decision"
            />
          ) : null}
        </div>
      </div>
      </div>
      )}
    </StepShell>
  );
}

function AnalysisPartitionRequiredShell({
  error,
  projectId,
  onRetry,
}: {
  error: EDAErrorState;
  projectId: string;
  onRetry: () => void;
}) {
  const guidedTitle = error.code
    ? EDA_READINESS_GUIDANCE[error.code]?.title
    : undefined;
  return (
    <section
      className="mx-auto max-w-5xl space-y-5 py-6"
      aria-labelledby="eda-analysis-partition-required-title"
      data-testid="eda-analysis-partition-required-shell"
      data-readiness-code={error.code ?? "analysis_partition_required"}
    >
      <div className="rounded-2xl border border-amber-300 bg-amber-50 p-6 shadow-sm">
        <div className="flex items-start gap-4">
          <span className="grid h-11 w-11 shrink-0 place-items-center rounded-xl bg-amber-100 text-amber-800">
            <ShieldCheck size={22} aria-hidden="true" />
          </span>
          <div className="min-w-0 space-y-2">
            <div className="text-xs font-bold uppercase tracking-[0.16em] text-amber-800">
              Governed EDA entry check
            </div>
            <h1
              id="eda-analysis-partition-required-title"
              className="text-xl font-bold text-slate-950"
            >
              {guidedTitle ?? "Analysis Partition required"}
            </h1>
            <p className="text-sm leading-6 text-slate-700">
              {error.message} ATLAS has not started the ordinary EDA Overview or
              documentation workflow. Target-directed analysis remains sealed
              until the development population is confirmed.
            </p>
          </div>
        </div>
      </div>

      <div className="rounded-2xl border border-slate-200 bg-white p-6 shadow-sm">
        <h2 className="font-semibold text-slate-950">Required next action</h2>
        <p className="mt-2 text-sm leading-6 text-slate-700">
          {error.recovery ??
            "Return to Data Acquisition and confirm the current Analysis Partition."}
        </p>
        <div className="mt-4 flex flex-wrap gap-2">
          <Link
            className="atlas-primary-button"
            to={projectWorkflowRoute(projectId, "/step01#analysis-partition-readiness")}
            data-testid="eda-analysis-partition-data-acquisition-action"
          >
            Return to Data Acquisition
            <ArrowRight size={15} aria-hidden="true" />
          </Link>
          {error.retryable !== false ? (
            <button
              type="button"
              className="atlas-secondary-button"
              onClick={onRetry}
              data-testid="eda-analysis-partition-retry"
            >
              <RefreshCw size={15} aria-hidden="true" />
              Recheck readiness
            </button>
          ) : null}
        </div>
      </div>

      <dl className="grid gap-3 rounded-2xl border border-slate-200 bg-slate-50 p-5 text-sm sm:grid-cols-3">
        <div>
          <dt className="text-xs font-semibold uppercase tracking-wide text-slate-500">
            Backend response
          </dt>
          <dd className="mt-1 font-semibold text-slate-900">
            HTTP {error.status ?? "unavailable"} · partial readiness
          </dd>
        </div>
        <div>
          <dt className="text-xs font-semibold uppercase tracking-wide text-slate-500">
            EDA analysis
          </dt>
          <dd className="mt-1 font-semibold text-amber-800">Not started</dd>
        </div>
        <div>
          <dt className="text-xs font-semibold uppercase tracking-wide text-slate-500">
            Final holdout
          </dt>
          <dd className="mt-1 font-semibold text-slate-900">
            Not admitted to the EDA UI
          </dd>
        </div>
      </dl>
    </section>
  );
}

function EDAUnavailablePanel({
  error,
  projectId,
  onRetry,
}: {
  error: EDAErrorState;
  projectId: string;
  onRetry: () => void;
}) {
  const guidedTitle = error.code
    ? EDA_READINESS_GUIDANCE[error.code]?.title
    : undefined;
  const presentation =
    error.domain === "analysis_partition"
      ? {
          title: guidedTitle ?? "Analysis Partition is not ready",
          summary:
            "The exact dataset remains selected, but governed EDA is paused until its development population and sealed final holdout are current.",
          action: "Review Analysis Partition",
          targetPath: "/step01#analysis-partition-readiness",
        }
      : error.domain === "identity"
        ? {
            title: guidedTitle ?? "Governed dataset identity needs attention",
            summary:
              "ATLAS could not verify the exact project, dataset, and Dataset Library version required for governed analysis.",
            action: "Review Data Acquisition",
            targetPath: "/step01",
          }
        : error.domain === "authorization"
          ? {
              title: "EDA access is not authorized",
              summary:
                "The governed request was rejected before analytical data was returned.",
              action: "Return to Data Acquisition",
              targetPath: "/step01",
            }
          : error.domain === "route"
            ? {
                title: "EDA service route is unavailable",
                summary: "The current FastAPI process does not expose the requested EDA workspace route.",
                action: "Return to Data Acquisition",
                targetPath: "/step01",
              }
            : error.domain === "server"
              ? {
                  title: "EDA service could not complete the request",
                  summary:
                    "The governed identity remains selected. This is a server execution failure, not evidence that the dataset is missing.",
                  action: "Return to Data Acquisition",
                  targetPath: "/step01",
                }
              : {
                  title: "EDA backend is unreachable",
                  summary:
                    "ATLAS could not receive a response for the exact governed request.",
                  action: "Return to Data Acquisition",
                  targetPath: "/step01",
                };
  return (
    <AtlasAttentionPanel title={presentation.title} tone="danger">
      <div className="space-y-3">
        <p>{presentation.summary}</p>
        <div className="rounded-lg border border-red-200 bg-white p-3 text-sm text-red-950">
          <div><strong>What failed:</strong> {error.message}</div>
          <div><strong>Endpoint:</strong> {error.endpoint}</div>
          <div><strong>Status:</strong> {error.status ?? "No response"}</div>
          <div><strong>Recovery:</strong> {error.recovery}</div>
        </div>
        <div className="flex flex-wrap gap-2">
          {error.retryable !== false ? (
            <button type="button" className="atlas-primary-button" onClick={onRetry}>
              <RefreshCw size={15} /> Retry exact request
            </button>
          ) : null}
          <Link
            className="atlas-secondary-button"
            to={projectWorkflowRoute(projectId, presentation.targetPath)}
          >
            {presentation.action}
          </Link>
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

function EdaTabQuickSummary({
  activeTab,
  activeTabLabel,
  items,
}: {
  activeTab: EDATab;
  activeTabLabel: string;
  items: EdaQuickSummaryItem[];
}) {
  return (
    <section
      className="eda-tab-quick-summary"
      aria-label={`${activeTabLabel} quick summary`}
      data-testid="eda-tab-quick-summary"
      data-active-tab={activeTab}
    >
      <div className="eda-tab-quick-summary__label">
        <span>{activeTabLabel}</span>
        <small>Quick summary</small>
      </div>
      <div className="eda-tab-quick-summary__items">
        {items.map((item) => (
          <div
            key={item.label}
            className={`eda-quick-summary-item eda-quick-summary-item--${
              item.tone ?? "neutral"
            }`}
            data-summary-label={item.label}
          >
            <small>{item.label}</small>
            <strong title={item.value}>{item.value}</strong>
          </div>
        ))}
      </div>
    </section>
  );
}

function EdaSectionNavigation({
  label,
  links,
}: {
  label: string;
  links: Array<{ id: string; label: string }>;
}) {
  return (
    <nav
      className="eda-section-navigation"
      aria-label={`${label} section navigation`}
      data-testid={`eda-${label.toLowerCase()}-section-navigation`}
    >
      <span className="eda-section-navigation__label">On this tab</span>
      <div className="eda-section-navigation__links">
        {links.map((link) => (
          <a key={link.id} href={`#${link.id}`}>
            {link.label}
          </a>
        ))}
      </div>
    </nav>
  );
}

function OverviewPanel({ data }: { data: WorkspaceResponse }) {
  const headline = safeObject(data.headline);
  const integrity = safeObject(data.data_integrity);
  const target = safeObject(data.target_profile);
  const constantColumns = safeArray(integrity.constant_columns);
  const identifierCandidates = safeArray(integrity.identifier_candidates);
  const leakageCandidates = safeArray(integrity.leakage_candidates);
  const invalidNumeric = safeArray(integrity.invalid_numeric_parsing);
  const targetSourceExcluded = safeArray<string>(data.target_source_excluded);
  const configuredTarget = String(data.target || "Not configured");
  const configuredEvent =
    data.event_value === null || data.event_value === undefined
      ? ""
      : String(data.event_value);
  const rows = Math.max(0, Number(headline.rows ?? data.row_count ?? 0));
  const predictors = Math.max(0, Number(headline.predictors ?? 0));
  const numericPredictors = Math.max(0, Number(headline.numeric_predictors ?? 0));
  const categoricalPredictors = Math.max(
    0,
    Number(headline.categorical_predictors ?? 0),
  );
  const missingRate = Math.max(
    0,
    Math.min(1, Number(headline.missing_cell_rate ?? 0)),
  );
  const duplicateRows = Math.max(0, Number(headline.duplicate_rows ?? 0));
  const duplicateRate = rows ? Math.min(1, duplicateRows / rows) : 0;
  const targetMissingCount = Math.max(0, Number(target.missing_count ?? 0));
  const numericShare = predictors ? (numericPredictors / predictors) * 100 : 0;
  const categoricalShare = predictors
    ? (categoricalPredictors / predictors) * 100
    : 0;
  const classRows = safeArray<any>(target.class_distribution);
  const maximumClassCount = Math.max(
    1,
    ...classRows.map((row) => Number(row.count ?? 0)),
  );
  const qualitySignals = [
    {
      label: "Completeness",
      value: Math.max(0, 1 - missingRate),
      display: formatPercent(Math.max(0, 1 - missingRate), 0),
      clear: missingRate === 0,
    },
    {
      label: "Row integrity",
      value: Math.max(0, 1 - duplicateRate),
      display: formatPercent(Math.max(0, 1 - duplicateRate), 0),
      clear: duplicateRows === 0,
    },
    {
      label: "Non-constant fields",
      value: predictors
        ? Math.max(0, 1 - constantColumns.length / predictors)
        : 0,
      display: predictors
        ? formatPercent(
            Math.max(0, 1 - constantColumns.length / predictors),
            0,
          )
        : "N/A",
      clear: predictors > 0 && constantColumns.length === 0,
    },
    {
      label: "Parsing-clear fields",
      value: predictors
        ? Math.max(0, 1 - invalidNumeric.length / predictors)
        : 0,
      display: predictors
        ? formatPercent(
            Math.max(0, 1 - invalidNumeric.length / predictors),
            0,
          )
        : "N/A",
      clear: predictors > 0 && invalidNumeric.length === 0,
    },
    {
      label: "Target completeness",
      value: rows
        ? Math.max(0, 1 - targetMissingCount / rows)
        : 0,
      display: rows
        ? formatPercent(Math.max(0, 1 - targetMissingCount / rows), 0)
        : "N/A",
      clear: rows > 0 && targetMissingCount === 0,
    },
  ];
  const clearQualityChecks = qualitySignals.filter((signal) => signal.clear).length;
  const readinessProgress = clearQualityChecks / qualitySignals.length;
  const targetHasNoUsablePopulation = Number(target.valid_count ?? 0) <= 0;
  const targetHasSingleClass =
    data.problem_type === "classification" &&
    Number(target.class_count ?? 0) < 2;
  const reviewIssueCount = [
    missingRate > 0,
    duplicateRows > 0,
    constantColumns.length > 0,
    identifierCandidates.length > 0,
    leakageCandidates.length > 0,
    invalidNumeric.length > 0,
    targetMissingCount > 0,
  ].filter(Boolean).length;
  const readinessLabel =
    targetHasNoUsablePopulation || targetHasSingleClass
      ? "Blocking target condition"
      : reviewIssueCount
        ? "Review items remain"
        : "Ready for analytical review";

  return (
    <div className="space-y-6" data-testid="eda-overview-launch-surface">
      <section
        className="eda-section-band overflow-hidden"
        aria-labelledby="eda-dataset-fingerprint-title"
        data-testid="eda-dataset-fingerprint"
      >
        <div className="grid lg:grid-cols-[minmax(0,1fr)_300px]">
          <div className="p-5 sm:p-6">
            <div className="flex flex-wrap items-center gap-2">
              <span className="rounded-full bg-blue-50 px-2.5 py-1 text-[10px] font-bold uppercase tracking-[0.14em] text-blue-700">
                Full Governed Population fingerprint
              </span>
              <span className="text-xs font-semibold text-slate-500">
                {data.dataset_version || "Current governed version"}
              </span>
            </div>
            <h2
              id="eda-dataset-fingerprint-title"
              className="mt-3 text-2xl font-bold tracking-tight text-slate-950"
            >
              One governed population, ready to interrogate
            </h2>
            <p className="mt-2 max-w-3xl text-sm leading-6 text-slate-600">
              This fingerprint connects population composition, target balance,
              structural quality, and authorization decisions before deeper analysis.
            </p>

            <div className="mt-6 grid gap-5 sm:grid-cols-3">
              <div>
                <div className="text-[11px] font-bold uppercase tracking-[0.12em] text-slate-500">
                  Registered population
                </div>
                <div className="mt-1 text-3xl font-bold tabular-nums text-slate-950">
                  {formatNumber(rows, 0)}
                </div>
                <div className="mt-1 text-xs text-slate-500">
                  Full backend rows · not a browser preview
                </div>
              </div>
              <div>
                <div className="text-[11px] font-bold uppercase tracking-[0.12em] text-slate-500">
                  Authorized predictors
                </div>
                <div className="mt-1 text-3xl font-bold tabular-nums text-slate-950">
                  {formatNumber(predictors, 0)}
                </div>
                <div className="mt-1 text-xs text-slate-500">
                  Target and source fields excluded
                </div>
              </div>
              <div>
                <div className="text-[11px] font-bold uppercase tracking-[0.12em] text-slate-500">
                  Modeling target
                </div>
                <div className="mt-1 break-words text-2xl font-bold text-blue-800">
                  {data.target}
                </div>
                <div className="mt-1 text-xs text-slate-500">
                  {titleCase(data.problem_type)} ·{" "}
                  {data.problem_type === "classification"
                    ? `event ${String(data.event_value ?? "configured")}`
                    : "continuous outcome"}
                </div>
              </div>
            </div>

            <div className="mt-6">
              <div className="mb-2 flex items-center justify-between gap-3 text-xs">
                <span className="font-semibold text-slate-700">
                  Predictor-type composition
                </span>
                <span className="text-slate-500">
                  {numericPredictors} numeric · {categoricalPredictors} categorical
                </span>
              </div>
              <div
                className="eda-fingerprint-composition flex h-4 overflow-hidden rounded-full bg-slate-100"
                role="img"
                aria-label={`${numericPredictors} numeric and ${categoricalPredictors} categorical predictors`}
              >
                <span
                  className="h-full bg-blue-600"
                  style={{ width: `${numericShare}%` }}
                />
                <span
                  className="h-full bg-cyan-500"
                  style={{ width: `${categoricalShare}%` }}
                />
              </div>
              <div className="mt-2 flex flex-wrap gap-4 text-xs text-slate-600">
                <span className="inline-flex items-center gap-1.5">
                  <span className="h-2.5 w-2.5 rounded-sm bg-blue-600" />
                  Numeric {formatPercent(numericShare / 100, 1)}
                </span>
                <span className="inline-flex items-center gap-1.5">
                  <span className="h-2.5 w-2.5 rounded-sm bg-cyan-500" />
                  Categorical {formatPercent(categoricalShare / 100, 1)}
                </span>
              </div>
            </div>
          </div>

          <div className="flex flex-col items-center justify-center border-t border-slate-200 bg-slate-50 p-6 text-center lg:border-l lg:border-t-0">
            <div
              className="eda-readiness-ring grid h-44 w-44 place-items-center rounded-full"
              style={{
                background: `conic-gradient(#2563eb ${readinessProgress * 360}deg, #dbe4ef 0deg)`,
              }}
              role="img"
              aria-label={`${clearQualityChecks} of ${qualitySignals.length} governed readiness checks are clear`}
            >
              <div className="grid h-36 w-36 place-items-center rounded-full bg-white">
                <div>
                  <div className="text-3xl font-bold tabular-nums text-slate-950">
                    {clearQualityChecks}/{qualitySignals.length}
                  </div>
                  <div className="text-[10px] font-bold uppercase tracking-[0.14em] text-slate-500">
                    Checks clear
                  </div>
                </div>
              </div>
            </div>
            <div className="mt-4 font-semibold text-slate-900">{readinessLabel}</div>
            <p className="mt-1 text-xs leading-5 text-slate-500">
              Categorical summary of server-returned checks; not a score,
              approval, or modeling decision.
            </p>
          </div>
        </div>
      </section>

      <div className="grid gap-6 xl:grid-cols-[1.08fr_0.92fr]">
        <section
          className="eda-section-band p-5 sm:p-6"
          aria-labelledby="eda-population-balance-title"
          data-testid="eda-overview-population-balance"
        >
          <div className="flex flex-col gap-2 sm:flex-row sm:items-start sm:justify-between">
            <div>
              <div className="text-[11px] font-bold uppercase tracking-[0.12em] text-blue-700">
                Development population
              </div>
              <h3 id="eda-population-balance-title" className="mt-1 text-lg font-bold text-slate-950">
                Target balance
              </h3>
              <p className="mt-1 text-sm text-slate-600">
                Development Population class prevalence for the configured event;
                the sealed final holdout is excluded.
              </p>
            </div>
            <span className="w-fit rounded-full bg-slate-100 px-2.5 py-1 text-xs font-semibold text-slate-600">
              Missing target {formatNumber(target.missing_count, 0)}
            </span>
          </div>

          {data.problem_type === "classification" ? (
            <div className="mt-5 space-y-4">
              {classRows.map((row, index) => {
                const count = Math.max(0, Number(row.count ?? 0));
                const rate = Number(row.rate ?? (rows ? count / rows : 0));
                const event =
                  String(row.value) === String(data.event_value ?? target.positive_class);
                return (
                  <div key={`${String(row.value)}-${index}`}>
                    <div className="mb-1.5 flex items-end justify-between gap-4">
                      <div>
                        <span className="font-semibold text-slate-900">
                          {event ? "Event" : "Non-event"}
                        </span>
                        <span className="ml-2 text-xs text-slate-500">
                          value {String(row.value)}
                        </span>
                      </div>
                      <div className="text-right">
                        <span className="font-bold tabular-nums text-slate-950">
                          {formatNumber(count, 0)}
                        </span>
                        <span className="ml-2 text-xs font-semibold tabular-nums text-slate-500">
                          {formatPercent(rate, 2)}
                        </span>
                      </div>
                    </div>
                    <div className="h-5 overflow-hidden rounded-md bg-slate-100">
                      <div
                        className={`h-full origin-left rounded-md motion-safe:animate-[eda-grow_620ms_cubic-bezier(0.2,0.75,0.25,1)_both] ${
                          event ? "bg-rose-500" : "bg-blue-600"
                        }`}
                        style={{ width: `${Math.max(2, (count / maximumClassCount) * 100)}%` }}
                      />
                    </div>
                  </div>
                );
              })}
              {target.rare_event ? (
                <div className="flex items-start gap-2 rounded-lg bg-amber-50 px-3 py-2 text-sm text-amber-900">
                  <AlertTriangle size={16} className="mt-0.5 shrink-0" />
                  Rare-event safeguards are required; accuracy is not an appropriate
                  primary metric for this distribution.
                </div>
              ) : null}
            </div>
          ) : (
            <div className="mt-4">
              <HistogramChart
                bins={chartBins(target)}
                source={target}
                scope="Development Population"
              />
            </div>
          )}
        </section>

        <section
          className="eda-section-band eda-section-band--tonal p-5 sm:p-6"
          aria-labelledby="eda-quality-health-title"
          data-testid="eda-data-quality-health"
        >
          <div className="text-[11px] font-bold uppercase tracking-[0.12em] text-blue-700">
            Data quality health
          </div>
          <h3 id="eda-quality-health-title" className="mt-1 text-lg font-bold text-slate-950">
            Structural signal skyline
          </h3>
          <p className="mt-1 text-sm text-slate-600">
            Five normalized checks show where review effort is concentrated.
          </p>
          <div
            className="eda-quality-skyline mt-6 grid h-44 grid-cols-5 items-end gap-3 border-b border-slate-300 px-2"
            role="img"
            aria-label={qualitySignals
              .map((signal) => `${signal.label} ${signal.display}`)
              .join(", ")}
          >
            {qualitySignals.map((signal) => (
              <span
                key={signal.label}
                className="relative min-h-4 rounded-t-md bg-blue-600"
                style={{ height: `${Math.max(8, signal.value * 100)}%` }}
                title={`${signal.label}: ${signal.display}`}
              >
                <span className="absolute -top-6 left-1/2 -translate-x-1/2 text-[10px] font-bold tabular-nums text-slate-700">
                  {signal.display}
                </span>
              </span>
            ))}
          </div>
          <div className="mt-2 grid grid-cols-5 gap-2 text-center text-[10px] font-semibold leading-4 text-slate-500">
            {qualitySignals.map((signal) => (
              <span key={signal.label}>{signal.label}</span>
            ))}
          </div>
          <div className="mt-5 grid grid-cols-2 gap-x-6 gap-y-3 text-sm">
            <div>
              <span className="text-slate-500">Missing cells</span>
              <div className="font-bold tabular-nums text-slate-900">
                {formatNumber(headline.missing_cells, 0)}
              </div>
            </div>
            <div>
              <span className="text-slate-500">Duplicate rows</span>
              <div className="font-bold tabular-nums text-slate-900">
                {formatNumber(duplicateRows, 0)}
              </div>
            </div>
          </div>
        </section>
      </div>

      <section
        className="eda-section-band overflow-hidden"
        aria-labelledby="eda-attention-title"
        data-testid="eda-overview-attention"
      >
        <div className="flex flex-col gap-2 border-b border-slate-200 bg-slate-50 px-5 py-4 sm:flex-row sm:items-center sm:justify-between">
          <div>
            <div className="text-[11px] font-bold uppercase tracking-[0.12em] text-blue-700">
              Decision queue
            </div>
            <h3 id="eda-attention-title" className="mt-1 text-lg font-bold text-slate-950">
              What deserves attention
            </h3>
          </div>
          <span className="text-xs text-slate-500">
            Warnings are review prompts, not automatic feature-removal decisions.
          </span>
        </div>
        <div className="divide-y divide-slate-100">
          <OverviewAttentionItem
            label="Duplicate rows"
            value={duplicateRows ? `${formatNumber(duplicateRows, 0)} require a recorded treatment decision` : "None detected"}
            tone={duplicateRows ? "warning" : "complete"}
          />
          <OverviewAttentionItem
            label="Constant fields"
            value={constantColumns.length ? `${constantColumns.length} detected` : "None detected"}
            tone={constantColumns.length ? "warning" : "complete"}
          />
          <OverviewAttentionItem
            label="Multicollinearity"
            value="Correlation and VIF review is available on Relationships"
            tone="review"
          />
          <OverviewAttentionItem
            label="Target-source exclusion"
            value={
              targetSourceExcluded.length
                ? `Data Acquisition target: ${configuredTarget}${configuredEvent ? ` (event ${configuredEvent})` : ""}. Target excluded from predictors; source field${targetSourceExcluded.length === 1 ? "" : "s"} ${targetSourceExcluded.join(", ")} also excluded by the server-authorized manifest.`
                : `Data Acquisition target: ${configuredTarget}${configuredEvent ? ` (event ${configuredEvent})` : ""}. Target excluded from predictors; no additional deterministic target-source field was returned.`
            }
            tone="complete"
          />
          <OverviewAttentionItem
            label="Bureau special values"
            value="Meaning-bearing special values remain visible for governed predictor review"
            tone="review"
          />
          <OverviewAttentionItem
            label="Unresolved findings"
            value="Reviewer dispositions and evidence are tracked on Findings"
            tone="review"
          />
        </div>
      </section>
    </div>
  );
}

function OverviewAttentionItem({
  label,
  value,
  tone,
}: {
  label: string;
  value: string;
  tone: "complete" | "review" | "warning";
}) {
  const config = {
    complete: {
      icon: <CheckCircle2 size={17} aria-hidden="true" />,
      label: "Completed",
      className: "bg-emerald-50 text-emerald-800",
    },
    review: {
      icon: <Activity size={17} aria-hidden="true" />,
      label: "Review",
      className: "bg-blue-50 text-blue-800",
    },
    warning: {
      icon: <AlertTriangle size={17} aria-hidden="true" />,
      label: "Attention",
      className: "bg-amber-50 text-amber-900",
    },
  }[tone];
  return (
    <div className="grid gap-3 px-5 py-3.5 sm:grid-cols-[190px_minmax(0,1fr)_auto] sm:items-center">
      <div className="font-semibold text-slate-900">{label}</div>
      <div className="text-sm leading-5 text-slate-600">{value}</div>
      <span
        className={`inline-flex w-fit items-center gap-1.5 rounded-full px-2.5 py-1 text-[11px] font-bold ${config.className}`}
      >
        {config.icon}
        {config.label}
      </span>
    </div>
  );
}

function PredictorsPanel({
  data,
  histogramBins,
  onHistogramBins,
  projectId,
  canonicalRequest,
  canonicalHandoff,
}: {
  data: WorkspaceResponse;
  histogramBins: number;
  onHistogramBins: (value: number) => void;
  projectId: string;
  canonicalRequest: Record<string, unknown>;
  canonicalHandoff: CanonicalDataAcquisitionEdaHandoff;
}) {
  const [search, setSearch] = useState("");
  const [sortMode, setSortMode] = useState("signal");
  const [rowLimit, setRowLimit] = useState(15);
  const allNumeric = safeArray<any>(data.numeric);
  const allCategorical = safeArray<any>(data.categorical);
  const selectedVariable = useEdaVisualSelection((state) => state.selectedVariable);
  const [selectedCategory, setSelectedCategory] = useState(() =>
    String(allCategorical[0]?.feature ?? ""),
  );
  const signalKey = data.problem_type === "classification" ? "iv" : "correlation_with_target";
  const sortRows = (rows: any[]) =>
    [...rows].sort((left, right) => {
      if (sortMode === "name") {
        return String(left.feature ?? "").localeCompare(String(right.feature ?? ""));
      }
      const key =
        sortMode === "missing"
          ? "missing_rate"
          : sortMode === "outliers"
            ? "outlier_rate"
            : signalKey;
      return Math.abs(Number(right?.[key] ?? 0)) - Math.abs(Number(left?.[key] ?? 0));
    });
  const normalizedSearch = search.trim().toLowerCase();
  const matchesSearch = (row: any) =>
    !normalizedSearch || String(row.feature ?? "").toLowerCase().includes(normalizedSearch);
  const numericMatches = sortRows(allNumeric.filter(matchesSearch));
  const categoricalMatches = sortRows(allCategorical.filter(matchesSearch));
  const allMissing = safeArray<any>(data.missingness).filter(
    (row: any) => Number(row.missing_count) > 0,
  );
  const missingMatches = sortRows(allMissing.filter(matchesSearch));
  const numeric = numericMatches.slice(0, rowLimit);
  const categorical = categoricalMatches.slice(0, rowLimit);
  const missing = missingMatches.slice(0, rowLimit);
  const searchActive = Boolean(normalizedSearch);
  const activeCategory =
    allCategorical.find((row: any) => row.feature === selectedCategory) ??
    allCategorical[0] ??
    null;
  const predictorAuthorization = safeObject(data.predictor_authorization);
  const predictorVisualProps = {
    predictorVisualProfiles: safeArray<any>(data.predictor_visual_profiles),
    predictorVisualContract: safeObject(data.predictor_visual_contract) as any,
    authorizedPredictors: safeArray<string>(
      predictorAuthorization.authorized_predictors,
    ),
    target: String(data.target ?? ""),
    targetSourceExcluded: safeArray<string>(
      data.target_source_excluded ??
        predictorAuthorization.target_source_excluded,
    ),
    rowCount: Number(data.row_count ?? 0),
    populationEventRate:
      Number.isFinite(Number(safeObject(data.target_profile).event_rate))
        ? Number(safeObject(data.target_profile).event_rate)
        : null,
    datasetVersion: String(data.dataset_version ?? ""),
  };

  useEffect(() => {
    if (!allCategorical.length) {
      if (selectedCategory) setSelectedCategory("");
      return;
    }
    if (!allCategorical.some((row: any) => row.feature === selectedCategory)) {
      setSelectedCategory(String(allCategorical[0].feature));
    }
  }, [allCategorical, selectedCategory]);

  return (
    <div className="space-y-4">
      <EdaSectionNavigation label="Predictors" links={predictorSectionLinks} />

      <div id="eda-predictors-signal" className="eda-section-anchor">
        <PredictorSignalLandscape {...predictorVisualProps} />
      </div>

      <div id="eda-predictors-deep-dive" className="eda-section-anchor">
        <PredictorDistributionExplorer
          projectId={projectId}
          datasetId={data.dataset_id}
          datasetVersionId={data.dataset_version_id}
          target={data.target}
          problemType={data.problem_type}
          eventValue={data.event_value}
          datasetVersion={data.dataset_version}
          predictors={allNumeric}
          histogramBins={histogramBins}
          onHistogramBins={onHistogramBins}
          canonicalRequest={canonicalRequest}
          canonicalHandoff={canonicalHandoff}
        />
      </div>

      <LazyPredictorSecondaryInsights {...predictorVisualProps} />

      <div id="eda-predictors-inventory" className="eda-section-anchor space-y-4">
      <AtlasWorkflowSection
        eyebrow="Predictor inventory"
        title="Detailed Predictor Profiles"
        description="Search, sort, and export governed predictor diagnostics. Counts, missingness, ordinary outliers, and distribution summaries use the Full Governed Population; IV, target correlation, event rates, monotonicity, and VIF use the Development Population."
        tone="info"
        action={
          <div className="flex flex-wrap gap-2" data-testid="predictor-inventory-scope">
            <span className="rounded-full border border-blue-200 bg-blue-50 px-2.5 py-1 text-[10px] font-semibold text-blue-800">
              Full Governed Population · structure
            </span>
            <span className="rounded-full border border-emerald-200 bg-emerald-50 px-2.5 py-1 text-[10px] font-semibold text-emerald-800">
              Development Population · target signal
            </span>
          </div>
        }
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

      {activeCategory ? (
        <AtlasWorkflowSection
          eyebrow="Categorical profile"
          title="Categorical Predictor Review"
          description="Category frequencies and structural quality use the Full Governed Population. Category target rates and IV use the Development Population; the sealed final holdout is excluded."
          tone="neutral"
          action={
            <span className="rounded-full border border-indigo-200 bg-indigo-50 px-2.5 py-1 text-[10px] font-semibold text-indigo-800">
              Governed mixed scope
            </span>
          }
        >
          <label className="mb-4 block max-w-md">
            <span className="atlas-label">Categorical predictor</span>
            <select
              className="atlas-input mt-1"
              value={String(activeCategory.feature)}
              onChange={(event) => setSelectedCategory(event.target.value)}
            >
              {allCategorical.map((row: any) => (
                <option key={row.feature} value={row.feature}>{row.feature}</option>
              ))}
            </select>
          </label>
          <div className="grid gap-4 xl:grid-cols-2">
            <CategoryFrequencyChart
              rows={safeArray<any>(activeCategory.top_levels)}
              scope="Full Governed Population"
            />
            <CategoryEventRateChart rows={safeArray<any>(activeCategory.top_levels)} />
            <div className="xl:col-span-2">
              <MetricGrid
                items={[
                  ["Rare levels", formatNumber(activeCategory.rare_level_count, 0)],
                  ["Cardinality", formatNumber(activeCategory.cardinality, 0)],
                  ["Missing", formatPercent(activeCategory.missing_rate)],
                  ["Suggested grouping", activeCategory.suggested_grouping ?? "Not evaluated"],
                ]}
              />
            </div>
          </div>
        </AtlasWorkflowSection>
      ) : null}

      <DataTable
        title="All numeric predictors"
        inventoryCount={{ shown: numeric.length, matched: numericMatches.length, total: allNumeric.length }}
        searchTerm={searchActive ? search : ""}
        onClearSearch={() => setSearch("")}
        highlightFeature={selectedVariable ?? ""}
        columns={[
          ["feature", "Feature"], ["count", "Count"], ["missing_rate", "Missing", "percent"], ["mean", "Mean"],
          ["standard_deviation", "Std. dev."], ["median", "Median"], ["skewness", "Skew"], ["outlier_rate", "Outliers", "percent"],
          [data.problem_type === "classification" ? "iv" : "correlation_with_target", data.problem_type === "classification" ? "IV (Development)" : "Target correlation (Development)"], ["monotonicity", "Monotonicity (Development)"],
        ]}
        rows={numeric}
        empty="No numeric predictors match the current search."
      />
      <DataTable
        title="All categorical predictors"
        inventoryCount={{ shown: categorical.length, matched: categoricalMatches.length, total: allCategorical.length }}
        searchTerm={searchActive ? search : ""}
        onClearSearch={() => setSearch("")}
        highlightFeature={String(activeCategory?.feature ?? "")}
        columns={[
          ["feature", "Feature"], ["count", "Count"], ["missing_rate", "Missing", "percent"], ["cardinality", "Cardinality"],
          ["rare_level_count", "Rare levels"], ["iv", "IV (Development)"], ["high_cardinality", "High cardinality", "boolean"], ["inconsistent_labels", "Label cleanup", "boolean"],
        ]}
        rows={categorical}
        empty="No categorical predictors match the current search."
      />
      <DataTable
        title="Missingness diagnostics"
        inventoryCount={{ shown: missing.length, matched: missingMatches.length, total: allMissing.length }}
        searchTerm={searchActive ? search : ""}
        onClearSearch={() => setSearch("")}
        highlightFeature={selectedVariable ?? String(activeCategory?.feature ?? "")}
        columns={[["feature", "Feature"], ["missing_count", "Missing rows (Full governed)"], ["missing_rate", "Missing (Full governed)", "percent"], ["missing_event_rate", "Event rate when missing (Development)", "percent"], ["present_event_rate", "Event rate when present (Development)", "percent"], ["informative_missingness", "Informative flag (Development)", "boolean"]]}
        rows={missing}
        empty="No missing predictor values were detected."
      />
      </div>
    </div>
  );
}

function RelationshipsPanel(props: {
  data: WorkspaceResponse;
  numericFields: string[];
  segmentFields: string[];
  pairwiseFeatures: string[];
  onPairwiseFeatures: (values: string[]) => void;
  projectId: string;
  canonicalRequest: Record<string, unknown>;
  canonicalHandoff: CanonicalDataAcquisitionEdaHandoff;
  onRun: (overrides?: Record<string, unknown>) => void;
}) {
  const columns = safeArray<string>(props.data.correlation_columns);
  const matrix = safeArray<Array<number | null>>(props.data.correlation_matrix);
  const pairwiseDisclosure = safeObject(props.data.pairwise_scope_disclosure);
  const selectedVariable = useEdaVisualSelection((state) => state.selectedVariable);
  const selectedRange = useEdaVisualSelection((state) => state.selectedRange);
  const pinnedPair = useEdaVisualSelection((state) => state.pinnedPair);
  const vifVariable = useEdaVisualSelection((state) => state.vifVariable);
  const setSelectedVariable = useEdaVisualSelection((state) => state.setSelectedVariable);
  const pinPair = useEdaVisualSelection((state) => state.pinPair);
  const setVifVariable = useEdaVisualSelection((state) => state.setVifVariable);
  const setRelationshipMode = useEdaVisualSelection((state) => state.setRelationshipMode);
  const vifByFeature = useMemo(
    () =>
      Object.fromEntries(
        safeArray<any>(props.data.vif).map((row) => [
          String(row.feature),
          {
            vif:
              row.vif === null || row.vif === undefined
                ? null
                : Number(row.vif),
            is_infinite: Boolean(row.is_infinite),
          },
        ]),
      ),
    [props.data.vif],
  );

  const simulateVif = useCallback(async (
    request: VifSimulationRequest,
  ): Promise<VifSimulationResult> => {
    const excludedFeature = request.temporarilyExcludedVariables[0];
    if (!excludedFeature) throw new Error("Select one predictor for the temporary VIF scenario.");
    const response = await fetch(`${API_BASE}/eda/vif-simulation`, {
      method: "POST",
      credentials: "include",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        problem_type: props.data.problem_type,
        excluded_feature: excludedFeature,
        ...props.canonicalRequest,
      }),
    });
    const payload = await response.json().catch(() => null);
    if (!response.ok || !payload?.ok) {
      const rawDetail = payload?.detail;
      const detail = safeObject(rawDetail);
      throw new Error(
        String(
          (typeof rawDetail === "string" ? rawDetail : detail.message) ??
            payload?.message ??
            payload?.error ??
            "The temporary VIF scenario could not be computed.",
        ),
      );
    }
    assertExactEdaResponseLineage(props.canonicalHandoff, payload);
    const summary = safeObject(payload.summary);
    const beforeRows = safeArray<any>(payload.before);
    const rows = safeArray<any>(payload.after);
    const currentMaximumVif = Number(summary.before_max_vif);
    const maximumVif = Number(summary.after_max_vif);
    return {
      summary: `Temporary exclusion of ${excludedFeature}; ${
        rows.length
      } predictors remain. No governed feature state was changed.`,
      currentMaximumVif: Number.isFinite(currentMaximumVif)
        ? currentMaximumVif
        : null,
      maximumVif: Number.isFinite(maximumVif) ? maximumVif : null,
      currentMaterialReviewCount: beforeRows.filter(
        (row) => Number(row.vif) >= 10,
      ).length,
      materialReviewCount: rows.filter((row) => Number(row.vif) >= 10).length,
      rows,
    };
  }, [
    props.data.event_value,
    props.data.dataset_id,
    props.data.dataset_version_id,
    props.data.problem_type,
    props.data.target,
    props.canonicalHandoff,
    props.canonicalRequest,
    props.projectId,
  ]);
  const generateVifResolutionPlan = useCallback(async (
    inputs: VifResolutionInputs,
  ): Promise<VifResolutionPlan> => {
    const response = await fetch(`${API_BASE}/eda/vif-resolution-plan`, {
      method: "POST",
      credentials: "include",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        problem_type: props.data.problem_type,
        intended_model_family: inputs.intendedModelFamily,
        target_vif_threshold: inputs.targetVifThreshold,
        resolution_objective: inputs.resolutionObjective,
        protected_predictors: inputs.protectedPredictors,
        allowed_actions: inputs.allowedActions,
        correlation_threshold: inputs.correlationThreshold,
        preference_weights: inputs.preferenceWeights,
        maximum_removals: inputs.maximumRemovals,
        ...props.canonicalRequest,
      }),
    });
    const payload = await response.json().catch(() => null);
    if (!response.ok || !payload?.ok) {
      const rawDetail = payload?.detail;
      const detail = safeObject(rawDetail);
      throw new Error(
        String(
          (typeof rawDetail === "string" ? rawDetail : detail.message) ??
            payload?.message ??
            "The VIF resolution plan could not be generated.",
        ),
      );
    }
    assertExactEdaResponseLineage(props.canonicalHandoff, payload);
    return normalizeVifResolutionPlan(payload);
  }, [
    props.data.dataset_id,
    props.data.dataset_version_id,
    props.data.event_value,
    props.data.problem_type,
    props.data.target,
    props.canonicalHandoff,
    props.canonicalRequest,
    props.projectId,
  ]);
  const decideVifResolutionPlan = useCallback(async (
    request: VifResolutionDecisionRequest,
  ) => {
    const response = await fetch(`${API_BASE}/eda/vif-resolution-plan/decision`, {
      method: "POST",
      credentials: "include",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        problem_type: props.data.problem_type,
        plan_id: request.planId,
        action: request.action,
        selected_cluster_ids: request.selectedClusterIds ?? [],
        rationale: request.rationale ?? "",
        modifications: request.modifications ?? {},
        ...props.canonicalRequest,
      }),
    });
    const payload = await response.json().catch(() => null);
    if (!response.ok || !payload?.ok) {
      const rawDetail = payload?.detail;
      const detail = safeObject(rawDetail);
      throw new Error(
        String(
          (typeof rawDetail === "string" ? rawDetail : detail.message) ??
            payload?.message ??
            "The VIF plan disposition could not be recorded.",
        ),
      );
    }
    assertExactEdaResponseLineage(props.canonicalHandoff, payload);
    return payload;
  }, [
    props.data.dataset_id,
    props.data.dataset_version_id,
    props.data.problem_type,
    props.canonicalHandoff,
    props.canonicalRequest,
    props.projectId,
  ]);
  const handleCorrelationVariable = useCallback(
    (name: string) => setSelectedVariable(name, "correlation"),
    [setSelectedVariable],
  );
  const handlePinnedPair = useCallback(
    (pair: { a: string; b: string }) => {
      setSelectedVariable(pair.a, "correlation");
      pinPair(pair);
      const nextPairwise = [pair.a, pair.b];
      props.onPairwiseFeatures(nextPairwise);
      props.onRun({ pairwise_features: nextPairwise });
    },
    [
      pinPair,
      props.onPairwiseFeatures,
      props.onRun,
      setSelectedVariable,
    ],
  );
  const handleVifVariable = useCallback(
    (variable: string | null) => setVifVariable(variable),
    [setVifVariable],
  );
  const launchRelationshipExplorer = useCallback(
    (mode: "2d" | "density" | "3d", pair?: { a: string; b: string }) => {
      const alreadyPinned =
        pair &&
        pinnedPair &&
        ((pinnedPair.a === pair.a && pinnedPair.b === pair.b) ||
          (pinnedPair.a === pair.b && pinnedPair.b === pair.a));
      if (pair && !alreadyPinned) handlePinnedPair(pair);
      setRelationshipMode(mode);
      window.requestAnimationFrame(() => {
        document
          .getElementById("eda-relationship-explorer-section")
          ?.scrollIntoView({ block: "start", behavior: "smooth" });
      });
    },
    [handlePinnedPair, pinnedPair, setRelationshipMode],
  );

  return (
    <div className="space-y-4">
      <EdaSectionNavigation
        label="Relationships"
        links={relationshipSectionLinks}
      />
      <div id="eda-relationships-correlation" className="eda-section-anchor">
      <AtlasWorkflowSection
        eyebrow="Association"
        title="Correlation and Redundancy"
        description="Search, filter, reorder, and pin an exact pair in the Development Population correlation matrix. Pairwise-complete ordinary values are used; nulls and governed special values are excluded, and the sealed final holdout is never accessed."
        tone="info"
      >
        <CorrelationExplorer
          columns={columns}
          matrix={matrix}
          correlationSampleSizes={safeArray<Array<number | null>>(
            props.data.correlation_n_matrix,
          )}
          vifByFeature={vifByFeature}
          selectedVariable={selectedVariable}
          pinnedPair={pinnedPair}
          onSelectVariable={handleCorrelationVariable}
          onPinPair={handlePinnedPair}
          onLaunch2D={(pair) => launchRelationshipExplorer("2d", pair)}
          onLaunch3D={(pair) => launchRelationshipExplorer("3d", pair)}
        />
      </AtlasWorkflowSection>
      </div>
      <div id="eda-relationships-strong-pairs" className="eda-section-anchor">
      <DataTable title="Strong correlated pairs · Development Population" columns={[["feature_a", "Feature A"], ["feature_b", "Feature B"], ["correlation", "Correlation (Development)"]]} rows={props.data.strong_pairs ?? []} empty="No Development Population pairs exceed the 0.70 review threshold." />
      </div>
      <div id="eda-relationships-vif" className="eda-section-anchor">
      <VifExplorer
        rows={safeArray<any>(props.data.vif)}
        correlationColumns={columns}
        correlationMatrix={matrix}
        selectedVariable={selectedVariable}
        onSelectVariable={handleVifVariable}
        datasetVersion={props.data.dataset_version}
        lineageKey={JSON.stringify(props.canonicalRequest)}
        scope={props.data.vif_scope}
        onSimulate={simulateVif}
        onGenerateResolutionPlan={generateVifResolutionPlan}
        onResolutionDecision={decideVifResolutionPlan}
      />
      </div>
      <section
        id="eda-relationship-explorer-section"
        className="eda-section-band overflow-hidden"
        aria-labelledby="eda-relationship-section-title"
        data-testid="eda-relationship-explorer-section"
      >
        <div className="flex flex-col gap-3 border-b border-indigo-100 bg-indigo-50/70 px-5 py-4 sm:flex-row sm:items-start sm:justify-between">
          <div className="flex min-w-0 items-start gap-3">
            <span className="rounded-lg bg-indigo-100 p-2 text-indigo-700">
              <Layers3 size={18} aria-hidden="true" />
            </span>
            <div>
              <div className="text-[11px] font-bold uppercase tracking-[0.12em] text-indigo-700">
                First-class linked analysis
              </div>
              <h2
                id="eda-relationship-section-title"
                className="mt-1 text-xl font-bold text-slate-950"
              >
                Relationship Explorer
              </h2>
              <p className="mt-1 max-w-4xl text-sm leading-6 text-slate-600">
                Move directly from Development Population correlation and VIF
                evidence into a bounded deterministic development sample. Use 2D
                Scatter, Density, or the lazily loaded 3D Explorer without changing
                governed data or accessing the sealed final holdout.
              </p>
            </div>
          </div>
          <button
            type="button"
            className="atlas-secondary-button shrink-0"
            onClick={() => launchRelationshipExplorer("2d")}
          >
            Focus 2D controls <ArrowRight size={15} aria-hidden="true" />
          </button>
        </div>
        <div className="border-b border-indigo-100 bg-white px-5 py-3 text-xs leading-5 text-indigo-950">
          {vifVariable ? (
            <>
              <strong>{vifVariable}</strong> is linked as X from VIF. Select Y
              and an explicit Z below.
            </>
          ) : (
            "Select a VIF row to link it as X, pin a heatmap pair to set X and Y, or choose axes directly below."
          )}
        </div>
        <React.Suspense
          fallback={
            <div
              className="flex min-h-64 items-center justify-center bg-white text-sm text-slate-600"
              role="status"
            >
              <LoaderCircle size={18} className="mr-2 animate-spin" />
              Loading the Relationship Explorer…
            </div>
          }
        >
          <RelationshipExplorer
            projectId={props.projectId}
            datasetId={props.data.dataset_id}
            datasetVersionId={props.data.dataset_version_id}
            target={String(props.data.target)}
            eventValue={props.data.event_value}
            problemType={props.data.problem_type}
            datasetVersion={String(props.data.dataset_version)}
            predictorManifestId={String(
              safeObject(props.data.predictor_authorization).manifest_version ?? "",
            )}
            numericFields={props.numericFields}
            segmentFields={props.segmentFields}
            selectedRange={selectedRange}
            initialPair={pinnedPair}
            vifVariable={vifVariable}
            canonicalHandoff={props.canonicalHandoff}
          />
        </React.Suspense>
      </section>
      <div id="eda-relationships-pairwise-plot" className="eda-section-anchor">
      <AtlasWorkflowSection
        eyebrow="Bounded chart data"
        title="Pairwise Plot Builder"
        description={safeArray<string>(props.data.pairwise_features).length ? `Development Population source: ${formatNumber(pairwiseDisclosure.population_rows, 0)} rows; ${formatNumber(pairwiseDisclosure.eligible_rows, 0)} complete-case rows eligible; ${formatNumber(pairwiseDisclosure.rows_excluded, 0)} excluded; ${formatNumber(pairwiseDisclosure.rendered_rows ?? props.data.pairwise_rows, 0)} deterministically rendered for visualization only. Sealed final holdout excluded.` : "Select predictors to generate a bounded visual sample from eligible Development Population rows. The sealed final holdout is excluded."}
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
            <button type="button" className="atlas-primary-button mt-3 w-full" onClick={() => props.onRun()}>Generate pairwise plot</button>
          </div>
          <div className="space-y-3">
            {safeArray<string>(props.data.pairwise_features).length ? (
              <>
                {Number(props.data.pairwise_event_rows ?? 0) < 5 && props.data.problem_type === "classification" ? <AtlasAttentionPanel title="Small event count in render sample" tone="warning">The pairwise render sample contains fewer than five event rows. Use the Development Population correlation and VIF metrics for analytical decisions.</AtlasAttentionPanel> : null}
                {selectedRange &&
                safeArray<string>(props.data.pairwise_features).includes(selectedRange.feature) ? (
                  <div
                    className="rounded-lg border border-blue-200 bg-blue-50 px-3 py-2 text-xs text-blue-950"
                    data-testid="pairwise-linked-range"
                  >
                    Linked highlight: rows where <strong>{selectedRange.feature}</strong> is
                    between {formatNumber(selectedRange.min, 3)} and{" "}
                    {formatNumber(selectedRange.max, 3)}. The full bounded sample remains
                    visible for context.
                  </div>
                ) : null}
                <PairwiseMatrix
                  features={safeArray<string>(props.data.pairwise_features)}
                  rows={safeArray<any>(props.data.pairwise_sample)}
                  selectedRange={selectedRange}
                />
              </>
            ) : (
              <AtlasAttentionPanel title="Pairwise plot data has not been generated" tone="info">Select up to four predictors and click Generate pairwise plot.</AtlasAttentionPanel>
            )}
          </div>
        </div>
      </AtlasWorkflowSection>
      </div>
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
  if (!hasTimeFields && !hasSegmentFields) {
    return (
      <StabilityUnavailableState
        title="No governed time or segment fields were detected"
        note="This dataset does not contain a governed observation-time or reusable segment field. Stability analysis can be enabled with a documented date, cohort, product, region, channel, or other approved segmentation variable."
      />
    );
  }
  return (
    <div
      className="space-y-4"
      data-testid="eda-stability-workspace"
      data-analysis-available="true"
    >
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
      {!hasTimeProfile && !hasSegmentProfile ? (
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

function StabilityUnavailableState({
  title,
  note,
}: {
  title: string;
  note: string;
}) {
  const capabilities: Array<{
    title: string;
    description: string;
    requirement: string;
    icon: LucideIcon;
  }> = [
    {
      title: "Time trend",
      description:
        "Volume and target behavior across governed observation periods.",
      requirement: "Requires an approved observation-date field.",
      icon: Activity,
    },
    {
      title: "Segment comparison",
      description:
        "Population and target behavior across reusable business groups.",
      requirement: "Requires an approved segment or cohort field.",
      icon: GitCompareArrows,
    },
    {
      title: "Population drift",
      description:
        "Reference-versus-comparison change once valid cohorts exist.",
      requirement: "Requires governed reference and comparison populations.",
      icon: ShieldCheck,
    },
    {
      title: "Population Stability Index (PSI)",
      description:
        "Distribution shift evidence using governed comparison windows.",
      requirement: "Requires valid time or cohort partitions.",
      icon: BarChart3,
    },
  ];
  return (
    <section
      className="eda-stability-unavailable"
      aria-labelledby="eda-stability-unavailable-title"
      data-testid="eda-stability-unavailable"
      data-analysis-available="false"
      data-confirmation-impact="non-blocking"
    >
      <div className="eda-stability-unavailable__header">
        <div className="flex min-w-0 items-start gap-3">
          <span className="eda-stability-unavailable__icon">
            <ShieldCheck size={19} aria-hidden="true" />
          </span>
          <div>
            <div className="eda-detail-label">Capability availability</div>
            <h2 id="eda-stability-unavailable-title">{title}</h2>
            <p>
              {note} ATLAS has not calculated stability, drift, or PSI, and it
              will not infer dates or comparison populations from ordinary
              numeric fields.
            </p>
          </div>
        </div>
        <span className="eda-stability-unavailable__status">
          Unavailable · No analysis fabricated
        </span>
      </div>

      <div
        className="eda-stability-capability-grid"
        aria-label="Unavailable stability capability previews"
      >
        {capabilities.map((capability) => {
          const Icon = capability.icon;
          return (
            <article
              key={capability.title}
              className="eda-stability-capability"
              aria-disabled="true"
              data-capability-state="unavailable"
            >
              <div className="eda-stability-capability__title">
                <Icon size={16} aria-hidden="true" />
                <h3>{capability.title}</h3>
              </div>
              <p>{capability.description}</p>
              <div>{capability.requirement}</div>
            </article>
          );
        })}
      </div>

      <div className="eda-stability-enablement">
        <div>
          <h3>How to enable these analyses</h3>
          <ol>
            <li>
              Register or derive a documented observation date, approved
              cohort, or reusable business segment upstream.
            </li>
            <li>
              Publish that governed field in a new dataset version and reopen
              this EDA workspace.
            </li>
            <li>
              Select the field here, then run the applicable time or segment
              analysis.
            </li>
          </ol>
        </div>
        <div className="eda-stability-nonblocking">
          <CheckCircle2 size={16} aria-hidden="true" />
          <span>
            This honest unavailable state is informational. It does not block
            EDA confirmation when the other required reviewer decisions are
            complete.
          </span>
        </div>
      </div>
    </section>
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
  if (!safeRows.length) return <ChartCard title="Category Event Rate" scope="Development Population"><div className="text-sm text-slate-500">Category event-rate data is not available.</div></ChartCard>;
  return (
    <ChartCard title="Category Event Rate" scope="Development Population · final holdout excluded">
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

function PairwiseMatrix({
  features,
  rows,
  selectedRange,
}: {
  features: string[];
  rows: any[];
  selectedRange?: EdaNumericRange | null;
}) {
  const safeFeatures = safeArray<string>(features).slice(0, 6);
  const safeRows = safeArray<any>(rows).slice(0, 600);
  const linkedRange =
    selectedRange && safeFeatures.includes(selectedRange.feature) ? selectedRange : null;
  if (safeFeatures.length < 2 || !safeRows.length) return <div className="rounded-lg border border-slate-200 bg-white p-4 text-sm text-slate-500">Pairwise plot data is not available for the selected features.</div>;
  return (
    <div
      className="overflow-auto rounded-lg border border-slate-200 bg-white p-3"
      data-linked-selection={linkedRange ? linkedRange.feature : undefined}
      role="region"
      aria-label={`Development Population bounded pairwise matrix for ${safeFeatures.join(", ")}; sealed final holdout excluded`}
    >
      <div className="grid min-w-[720px] gap-1" style={{ gridTemplateColumns: `120px repeat(${safeFeatures.length}, minmax(120px, 1fr))` }}>
        <div />
        {safeFeatures.map((feature) => <div key={`head-${feature}`} className="truncate px-2 py-1 text-center text-[10px] font-semibold uppercase text-slate-500" title={feature}>{feature}</div>)}
        {safeFeatures.flatMap((yFeature) => [
          <div key={`row-${yFeature}`} className="truncate px-2 py-10 text-[10px] font-semibold uppercase text-slate-500" title={yFeature}>{yFeature}</div>,
          ...safeFeatures.map((xFeature) => (
            <div key={`${yFeature}-${xFeature}`} className="h-32 rounded border border-slate-100 bg-slate-50">
              {xFeature === yFeature ? (
                <MiniHistogramValues
                  rows={safeRows}
                  feature={xFeature}
                  selectedRange={linkedRange}
                />
              ) : (
                <ScatterCell
                  rows={safeRows}
                  xFeature={xFeature}
                  yFeature={yFeature}
                  selectedRange={linkedRange}
                />
              )}
            </div>
          )),
        ])}
      </div>
    </div>
  );
}

function MiniHistogramValues({
  rows,
  feature,
  selectedRange,
}: {
  rows: any[];
  feature: string;
  selectedRange?: EdaNumericRange | null;
}) {
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
  const binWidth = max === min ? 0 : (max - min) / bins.length;
  return (
    <div className="flex h-full items-end gap-0.5 p-2">
      {bins.map((count, index) => {
        const lower = min + index * binWidth;
        const upper = index === bins.length - 1 ? max : lower + binWidth;
        const linked =
          selectedRange?.feature === feature &&
          upper >= selectedRange.min &&
          lower <= selectedRange.max;
        return (
          <span
            key={index}
            className={`block flex-1 rounded-t transition-colors ${
              selectedRange?.feature === feature
                ? linked
                  ? "bg-blue-700"
                  : "bg-slate-300"
                : "bg-blue-400"
            }`}
            style={{ height: `${Math.max(4, (count / maxBin) * 100)}%` }}
          />
        );
      })}
    </div>
  );
}

function ScatterCell({
  rows,
  xFeature,
  yFeature,
  selectedRange,
}: {
  rows: any[];
  xFeature: string;
  yFeature: string;
  selectedRange?: EdaNumericRange | null;
}) {
  const points = safeArray<any>(rows)
    .map((row) => {
      const linkedValue = selectedRange ? Number(row[selectedRange.feature]) : Number.NaN;
      return {
        x: Number(row[xFeature]),
        y: Number(row[yFeature]),
        event: !!row.__event__,
        linked:
          !selectedRange ||
          (Number.isFinite(linkedValue) &&
            linkedValue >= selectedRange.min &&
            linkedValue <= selectedRange.max),
      };
    })
    .filter((point) => Number.isFinite(point.x) && Number.isFinite(point.y));
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
          className={`absolute rounded-full transition-[opacity,transform] ${
            point.event ? "bg-emerald-600" : "bg-blue-500"
          }`}
          data-linked-match={selectedRange ? (point.linked ? "true" : "false") : undefined}
          style={{
            left: `${scale(point.x, xMin, xMax)}%`,
            bottom: `${scale(point.y, yMin, yMax)}%`,
            width: point.linked && selectedRange ? "0.5rem" : "0.375rem",
            height: point.linked && selectedRange ? "0.5rem" : "0.375rem",
            opacity: selectedRange ? (point.linked ? 0.9 : 0.12) : 0.6,
            transform: point.linked && selectedRange ? "translate(-1px, 1px)" : undefined,
          }}
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
                            <div className="font-semibold text-slate-900">{display}</div>
                            <div className="mt-1.5 h-1.5 overflow-hidden rounded-full bg-slate-100">
                              <div className={`h-full rounded-full ${/vif/i.test(key) && numeric >= 10 ? "bg-rose-500" : /vif/i.test(key) && numeric >= 5 ? "bg-amber-500" : "bg-blue-600"}`} style={{ width: `${width}%` }} />
                            </div>
                          </div>
                        ) : type === "percent" ? (
                          <span className="font-medium tabular-nums text-slate-800">{display}</span>
                        ) : (
                          <span className={typeof row?.[key] === "number" ? "tabular-nums text-slate-800" : ""}>{display}</span>
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

function titleCase(value: string) {
  return value ? `${value.charAt(0).toUpperCase()}${value.slice(1)}` : "Not available";
}
