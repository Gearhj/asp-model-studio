// EDA Target Intelligence -- shared types and pure display logic.
//
// The Target tab previously restated Overview: the same class counts, the same
// one-line rare-event sentence, and two group tables. This module holds the
// non-visual half of the replacement -- the vocabulary, the honest-absence
// rules for governance narrative, and the bounded evidence payload shape.
//
// Deliberately contains NO statistics. The event rate, the imbalance tier, and
// the Wilson interval are all computed once on the server over the governed
// artifact (server/analytics/target_intelligence_service.py) so the browser can
// never present a second, differently-rounded answer.
import type { ProjectContext } from "./projectContext";

// ---------------------------------------------------------------------------
// Analysis Scope -- the governance contract, derived by the server
// ---------------------------------------------------------------------------
//
// The browser NEVER decides whether an analysis is governed. Every field below
// is read from the server response; nothing here is computed locally, and
// nothing here is sent back as an assertion. See
// server/analytics/analysis_scope.py for the authoritative definition.

export type AnalysisScopeMode = "governed_version" | "workspace_draft";

export type AnalysisScope = {
  contractVersion: string;
  mode: AnalysisScopeMode;
  label: string;
  projectId: string;
  datasetId: string | null;
  datasetVersionId: string | null;
  workspaceDatasetId: string | null;
  datasetName: string;
  datasetFingerprint: string | null;
  artifactChecksum: string | null;
  target: string;
  populationRows: number;
  exact: boolean;
  sampled: boolean;
  immutableVersion: boolean;
  analysisSource: string;
  evidenceEligible: boolean;
  mddEligible: boolean;
  disclosure: string;
  resolvedAt: string;
  suggestedGovernedSource?: { datasetId: string | null; versionId: string | null } | null;
};

export const GOVERNED_VERSION: AnalysisScopeMode = "governed_version";
export const WORKSPACE_DRAFT: AnalysisScopeMode = "workspace_draft";

/** Markers a downloaded draft summary must carry so it cannot be mistaken for
 *  an approved artifact. Mirrors analysis_scope.DRAFT_EXPORT_MARKERS. */
export const DRAFT_EXPORT_MARKERS = [
  "Workspace Draft",
  "Not Governed Evidence",
  "Not Version-Pinned",
  "Not MDD Eligible",
];

export function isGovernedScope(scope: AnalysisScope | null | undefined): boolean {
  return scope?.mode === GOVERNED_VERSION;
}

/** Identity used for scope-sensitive stale-result rejection. Mirrors
 *  analysis_scope.scope_identity so a draft result can never satisfy a
 *  governed request. */
export function scopeIdentity(scope: AnalysisScope | null | undefined): string {
  if (!scope) return "scope:none";
  return [
    "scope",
    scope.mode,
    scope.projectId ?? "",
    scope.datasetId ?? "",
    scope.datasetVersionId ?? "",
    scope.datasetFingerprint ?? "",
    scope.artifactChecksum ?? "",
    scope.target ?? "",
  ].join("|");
}

/** Why the governed evidence action is unavailable, in the user's terms.
 *  Returned as text so it can be rendered inline -- never as a tooltip only. */
export function evidenceDisabledReason(
  scope: AnalysisScope | null | undefined,
  resolving: boolean
): string | null {
  if (resolving) return "Resolving the registered dataset version. Governed evidence is available once it completes.";
  if (!scope) return "Analytical scope has not been resolved yet, so governed evidence cannot be saved.";
  if (scope.mode === WORKSPACE_DRAFT) {
    return (
      "This is a Workspace Draft Analysis. It is not pinned to an immutable dataset version, so it cannot be " +
      "saved as governed evidence. Register or link a Dataset Library version on Data Acquisition, then rerun " +
      "the analysis against that version."
    );
  }
  if (!scope.evidenceEligible) return "The resolved analytical scope is not eligible for governed evidence.";
  return null;
}

// ---------------------------------------------------------------------------
// Server result shapes
// ---------------------------------------------------------------------------

export type ImbalanceSeverity = "none" | "low" | "medium" | "high" | "critical" | "unknown";

/** Tiering of the CONFIGURED event's prevalence. Orientation-sensitive. */
export type EventPrevalence = {
  label: string;
  severity: ImbalanceSeverity;
  eventRate: number | null;
  nonEventRate: number | null;
  eventIsRare: boolean | null;
  eventIsMajority: boolean | null;
  singleClass: boolean | null;
  rule: string;
  thresholds: Array<{ label: string; minEventRate: number; severity: ImbalanceSeverity; rare: boolean }>;
};

/** Tiering of how uneven the classes are. Orientation-independent. */
export type ClassImbalance = {
  label: string;
  severity: ImbalanceSeverity;
  minorityShare: number | null;
  minorityClass: "event" | "non_event" | null;
  minorityCount: number | null;
  majorityCount: number | null;
  majorityToMinorityRatio: number | null;
  rule: string;
  thresholds: Array<{ label: string; minMinorityShare: number; severity: ImbalanceSeverity }>;
};

export type ImbalanceAssessment = {
  /** Headline: the prevalence tier of the configured event. */
  label: string;
  severity: ImbalanceSeverity;
  eventPrevalence: EventPrevalence;
  classImbalance: ClassImbalance;
  nonEventsPerEvent: number | null;
  eventsPerNonEvent: number | null;
  majorityToMinorityRatio: number | null;
  /** Alias of nonEventsPerEvent, kept for existing callers. Always rendered
   *  alongside `ratioOrientation` -- never as a bare "imbalance ratio". */
  imbalanceRatio: number | null;
  ratioOrientation: string;
  eventToNonEventRatio: number | null;
  minorityShare: number | null;
  minorityClass: "event" | "non_event" | null;
  minorityCount?: number | null;
  eventIsRare: boolean | null;
  eventIsMajority: boolean | null;
  singleClass: boolean | null;
  rule: string;
  implications: string[];
  thresholds: Array<{ label: string; minMinorityShare: number; severity: ImbalanceSeverity }>;
  prevalenceThresholds: Array<{ label: string; minEventRate: number; severity: ImbalanceSeverity; rare: boolean }>;
};

export type ConfidenceInterval = {
  method: string;
  confidenceLevel: number;
  z: number;
  eventCount: number;
  totalCount: number;
  pointEstimate: number | null;
  lowerBound: number | null;
  upperBound: number | null;
  halfWidth?: number;
  explanation: string;
};

export type TargetClassBalance = {
  target: string;
  eventValue: string | null;
  nonEventValue: string | null;
  eventCount: number;
  nonEventCount: number;
  eventRate: number | null;
  nonEventRate: number | null;
  eventToNonEventRatio: number | null;
  imbalanceRatio: number | null;
  missingTargetCount: number;
  totalModelingPopulation: number;
  classCount: number;
  resolution: "exact" | "sampled" | "unsupported";
  /** "configured" | "minority_fallback" | "requested_value_absent" | "single_class".
   *  Anything other than "configured" means the analysed event is not the one
   *  the project configured, which the UI must disclose. */
  eventValueResolution?: string;
  requestedEventValue?: string | null;
};

export type TargetAssessmentResult = {
  ok: boolean;
  supported: boolean;
  reason?: string;
  datasetId?: string;
  versionId?: string;
  target?: string;
  analysisScope: AnalysisScope | null;
  scopeIdentity?: string;
  classBalance: TargetClassBalance | null;
  imbalance: ImbalanceAssessment | null;
  confidenceInterval: ConfidenceInterval | null;
  cached?: boolean;
  distribution?: {
    classDistribution: Array<{ value: unknown; count: number; percent: number }>;
    resolution: "exact" | "sampled" | "unsupported";
    durationMs: number;
    cached: boolean;
    sampling?: { samplingMethod: string; seed: number; sampledRowCount: number; sourceRowCount: number };
  };
};

export type TargetPredictorAnalysisType = "numeric_quantile" | "categorical";

export type TargetPredictorGroup = {
  /** Numeric bands carry `label` (Q1..Qn); categorical groups carry `category`. */
  label?: string;
  category?: string;
  band?: number;
  population: number;
  eventCount: number;
  eventRate: number | null;
  lowerBound?: number | null;
  upperBound?: number | null;
  meanValue?: number | null;
  isMissingGroup?: boolean;
  isOtherGroup?: boolean;
  collapsedCategoryCount?: number;
  smallGroup: boolean;
};

export type TargetPredictorSummary = {
  highest: { label: string; eventRate: number; eventCount: number; population: number } | null;
  lowest: { label: string; eventRate: number; eventCount: number; population: number } | null;
  eventRateSpread: number | null;
  eventRateRatio: number | null;
  monotonicity: string;
  eventConcentration: number | null;
  missingEffect: {
    missingPopulation: number;
    missingEventCount: number;
    missingEventRate: number | null;
    presentEventRate: number | null;
    difference: number | null;
    materialDifference: boolean;
  } | null;
  smallGroupCount: number;
  limitations: string[];
  interpretation: string;
};

export type TargetPredictorBoxPlot = {
  targetClass: "event" | "non_event";
  label: string;
  population: number;
  minimum: number | null;
  q1: number | null;
  median: number | null;
  q3: number | null;
  maximum: number | null;
  whiskerLow: number | null;
  whiskerHigh: number | null;
  outlierCount: number;
};

export type TargetByPredictorResult = {
  ok: boolean;
  supported: boolean;
  /** Null on the draft path -- a workspace analysis has no governed identity
   *  and must never invent one. */
  datasetId: string | null;
  versionId: string | null;
  analysisScope: AnalysisScope | null;
  scopeIdentity?: string;
  target: string;
  predictor: string;
  analysisType: TargetPredictorAnalysisType;
  eventValue: string;
  includeMissing: boolean;
  rows: TargetPredictorGroup[];
  missingGroup: TargetPredictorGroup | null;
  otherGroup: TargetPredictorGroup | null;
  populationEventRate: number | null;
  analyzedRowCount: number;
  analyzedEventCount: number;
  summary: TargetPredictorSummary;
  boxPlotByTarget?: TargetPredictorBoxPlot[];
  resolution: "exact";
  cached: boolean;
  durationMs: number;
  requestedBands?: number;
  returnedBands?: number;
  requestedTopCategories?: number;
  returnedCategories?: number;
  distinctCategoryCount?: number;
  topNApplied?: boolean;
  rareCategoryWarning?: boolean;
};

export type TargetFindingScopeMode = "governed_version" | "workspace_draft" | "legacy_unscoped";

export type TargetFinding = {
  targetFindingId: string;
  projectId: string;
  scopeMode: TargetFindingScopeMode;
  /** "Governed Finding" | "Draft Finding" | "Legacy Finding (scope unknown)" */
  scopeLabel: string;
  governed: boolean;
  /** Null unless the finding is genuinely governed. */
  datasetId: string | null;
  versionId: string | null;
  artifactChecksum: string | null;
  workspaceFingerprint: string | null;
  promotedFromFindingId?: string | null;
  promotedAt?: string | null;
  target: string;
  analysisType: string;
  title: string;
  detail: string;
  severity: "info" | "review" | "warning" | "blocker";
  status: "open" | "reviewed" | "resolved";
  createdByUserId?: string;
  createdAt: string;
  updatedAt: string;
  metadata?: Record<string, unknown>;
};

// ---------------------------------------------------------------------------
// Part C: governance narrative, shown honestly
// ---------------------------------------------------------------------------

/** Narrative excerpt length before a "View full governance definition" is offered. */
export const NARRATIVE_EXCERPT_LENGTH = 180;

export const GOVERNANCE_ABSENT_LABEL = "Not recorded in Project Context";

export type GovernanceField = {
  key: string;
  label: string;
  value: string;
  present: boolean;
  excerpt: string;
  truncated: boolean;
};

function normalize(value: unknown): string {
  return typeof value === "string" ? value.trim() : "";
}

/**
 * Builds an excerpt plus a truncation flag.
 *
 * Cuts on a word boundary so a governance definition is never shown ending
 * mid-word, which reads as corrupted data rather than as an excerpt.
 */
export function narrativeExcerpt(value: string, limit = NARRATIVE_EXCERPT_LENGTH): { excerpt: string; truncated: boolean } {
  const text = value.replace(/\s+/g, " ").trim();
  if (text.length <= limit) return { excerpt: text, truncated: false };
  const cut = text.slice(0, limit);
  const boundary = cut.lastIndexOf(" ");
  return { excerpt: `${(boundary > limit * 0.6 ? cut.slice(0, boundary) : cut).trimEnd()}...`, truncated: true };
}

/**
 * The governance narrative that describes the target, read from the durable
 * backend Project Context. Absent fields are reported as absent -- this never
 * substitutes a placeholder or invents a definition.
 */
export function buildTargetGovernanceFields(context: ProjectContext | null): GovernanceField[] {
  const source: Array<[string, string, string]> = [
    ["targetDefinition", "Business target definition", normalize(context?.targetDefinition)],
    ["populationDefinition", "Population definition", normalize(context?.populationDefinition)],
    ["observationWindow", "Observation window", normalize(context?.observationWindow)],
    ["performanceWindow", "Performance window", normalize(context?.performanceWindow)],
    ["businessObjective", "Business objective", normalize(context?.businessObjective)],
    ["intendedModelUse", "Intended model use", normalize(context?.intendedModelUse)],
    ["approvedUses", "Approved uses", normalize(context?.fraudDetails?.approvedUses)],
    ["prohibitedUses", "Prohibited uses", normalize(context?.fraudDetails?.prohibitedUses)],
    ["humanReviewRequired", "Human review required", normalize(context?.fraudDetails?.humanReviewRequired)],
    ["overrideAuthority", "Override authority", normalize(context?.fraudDetails?.overrideAuthority)],
    ["modelingMissionSummary", "Accepted modeling mission", normalize(context?.modelingMissionSummary)],
  ];
  return source.map(([key, label, value]) => {
    const { excerpt, truncated } = narrativeExcerpt(value);
    return { key, label, value, present: value.length > 0, excerpt, truncated };
  });
}

/** Governance fields that describe the TARGET specifically and are still blank. */
export const TARGET_GOVERNANCE_REQUIRED_KEYS = [
  "targetDefinition",
  "populationDefinition",
  "observationWindow",
  "performanceWindow",
] as const;

export function unresolvedGovernanceGaps(fields: GovernanceField[]): GovernanceField[] {
  const required = new Set<string>(TARGET_GOVERNANCE_REQUIRED_KEYS);
  return fields.filter((field) => required.has(field.key) && !field.present);
}

// ---------------------------------------------------------------------------
// Display helpers
// ---------------------------------------------------------------------------

export const IMBALANCE_TONES: Record<ImbalanceSeverity, "success" | "info" | "warning" | "danger" | "neutral"> = {
  none: "success",
  low: "info",
  medium: "warning",
  high: "warning",
  critical: "danger",
  unknown: "neutral",
};

export function formatRatio(value: number | null | undefined, digits = 1): string {
  if (value === null || value === undefined || !Number.isFinite(value)) return "Not available";
  return `${value.toLocaleString(undefined, { maximumFractionDigits: digits, minimumFractionDigits: digits })} : 1`;
}

export function formatCount(value: number | null | undefined): string {
  if (value === null || value === undefined || !Number.isFinite(value)) return "Not available";
  return Math.round(value).toLocaleString();
}

/** Text equivalent of the interval, used for the visible caption and the a11y summary. */
export function describeConfidenceInterval(
  interval: ConfidenceInterval | null,
  formatRate: (rate: number | null | undefined) => string
): string {
  if (!interval || interval.pointEstimate === null) return "The event-rate confidence interval is not available.";
  return (
    `${formatRate(interval.pointEstimate)} observed event rate, ` +
    `${(interval.confidenceLevel * 100).toFixed(0)}% ${interval.method}: ` +
    `${formatRate(interval.lowerBound)} to ${formatRate(interval.upperBound)} ` +
    `(${interval.eventCount.toLocaleString()} events in ${interval.totalCount.toLocaleString()} rows).`
  );
}

export function describeTargetByPredictor(
  result: TargetByPredictorResult | null,
  formatRate: (rate: number | null | undefined) => string
): string {
  if (!result) return "No target-by-predictor analysis has been run.";
  const label = (group: TargetPredictorGroup) => group.category ?? group.label ?? "Group";
  const parts = [
    `Event rate for ${result.target} by ${result.predictor}, ${result.rows.length} groups.`,
    ...result.rows.map((row) => `${label(row)}: ${formatRate(row.eventRate)} over ${row.population.toLocaleString()} rows.`),
  ];
  if (result.missingGroup) {
    parts.push(`Missing: ${formatRate(result.missingGroup.eventRate)} over ${result.missingGroup.population.toLocaleString()} rows.`);
  }
  if (result.otherGroup) {
    parts.push(`Other (${result.otherGroup.collapsedCategoryCount} collapsed categories): ${formatRate(result.otherGroup.eventRate)}.`);
  }
  return parts.join(" ");
}

// ---------------------------------------------------------------------------
// Part J: bounded evidence payload
// ---------------------------------------------------------------------------

/** Mirrors the server-side cap in target_intelligence_router.MAX_EVIDENCE_ROWS.
 *  Evidence summarizes an analysis; it never carries the population. */
export const EVIDENCE_MAX_ROWS = 60;

export type TargetEvidenceInput = {
  projectId: string;
  datasetId: string;
  versionId: string;
  datasetName: string;
  target: string;
  scope: AnalysisScope | null;
  assessment: TargetAssessmentResult | null;
  governance: GovernanceField[];
  predictorAnalysis: TargetByPredictorResult | null;
  timeField: string;
  segmentField: string;
  chartSpecification: Record<string, unknown>;
  userId: string;
  capturedAt: string;
};

/**
 * Builds the bounded analytical summary used for the DOWNLOADABLE export.
 *
 * Governed EVIDENCE is not built here -- it is built server-side by
 * POST /api/analytics/target-evidence, which re-resolves every governance fact
 * rather than trusting the browser. This function produces the local export
 * only, and stamps a draft export so it cannot pass for an approved artifact.
 */
export function buildTargetEvidencePayload(input: TargetEvidenceInput): Record<string, unknown> {
  const balance = input.assessment?.classBalance ?? null;
  const draftDisclosure =
    "Workspace Draft. Not governed evidence, not version-pinned, not MDD eligible.";
  const draftScope = input.scope
    ? {
        contractVersion: input.scope.contractVersion,
        mode: WORKSPACE_DRAFT,
        label: "Workspace Draft Analysis",
        projectId: input.projectId,
        datasetId: null,
        datasetVersionId: null,
        workspaceDatasetId: input.scope.workspaceDatasetId ?? null,
        datasetName: input.datasetName,
        datasetFingerprint: input.scope.datasetFingerprint ?? null,
        artifactChecksum: null,
        target: input.target,
        populationRows: input.scope.populationRows,
        exact: input.scope.exact,
        sampled: input.scope.sampled,
        immutableVersion: false,
        analysisSource: "target_intelligence.local_draft_export",
        evidenceEligible: false,
        mddEligible: false,
        disclosure: draftDisclosure,
        resolvedAt: input.capturedAt,
      }
    : null;
  const rows = (input.predictorAnalysis?.rows ?? []).slice(0, EVIDENCE_MAX_ROWS).map((row) => ({
    group: row.category ?? row.label ?? "",
    population: row.population,
    eventCount: row.eventCount,
    eventRate: row.eventRate,
    smallGroup: row.smallGroup,
  }));
  return {
    // Scope first, so the very top of a downloaded file states what it is.
    analysisScope: draftScope,
    scopeMode: WORKSPACE_DRAFT,
    governed: false,
    evidenceEligible: false,
    mddEligible: false,
    markers: DRAFT_EXPORT_MARKERS,
    disclosure: draftDisclosure,
    datasetIdentity: {
      datasetId: null,
      versionId: null,
      workspaceFingerprint: input.scope?.datasetFingerprint ?? null,
      artifactChecksum: null,
      datasetName: input.datasetName,
    },
    generatedAt: input.capturedAt,
    targetDefinition: {
      target: input.target,
      eventValue: balance?.eventValue ?? null,
      nonEventValue: balance?.nonEventValue ?? null,
      governance: input.governance
        .filter((field) => field.present)
        .map((field) => ({ key: field.key, label: field.label, value: field.value })),
      unresolvedGaps: unresolvedGovernanceGaps(input.governance).map((field) => field.key),
    },
    classCounts: {
      eventCount: balance?.eventCount ?? null,
      nonEventCount: balance?.nonEventCount ?? null,
      missingTargetCount: balance?.missingTargetCount ?? null,
      totalModelingPopulation: balance?.totalModelingPopulation ?? null,
    },
    eventRate: balance?.eventRate ?? null,
    imbalanceAssessment: input.assessment?.imbalance
      ? {
          label: input.assessment.imbalance.label,
          severity: input.assessment.imbalance.severity,
          imbalanceRatio: input.assessment.imbalance.imbalanceRatio,
          rule: input.assessment.imbalance.rule,
        }
      : null,
    confidenceInterval: input.assessment?.confidenceInterval ?? null,
    selectedPredictorAnalysis: input.predictorAnalysis
      ? {
          predictor: input.predictorAnalysis.predictor,
          analysisType: input.predictorAnalysis.analysisType,
          rows,
          truncatedRows: (input.predictorAnalysis.rows?.length ?? 0) > EVIDENCE_MAX_ROWS,
          missingGroup: input.predictorAnalysis.missingGroup
            ? {
                population: input.predictorAnalysis.missingGroup.population,
                eventCount: input.predictorAnalysis.missingGroup.eventCount,
                eventRate: input.predictorAnalysis.missingGroup.eventRate,
              }
            : null,
          summary: input.predictorAnalysis.summary,
        }
      : null,
    timeAndSegmentSelection: {
      timeField: input.timeField || null,
      segmentField: input.segmentField || null,
    },
    resolution: {
      state: balance?.resolution ?? "unsupported",
      exact: balance?.resolution === "exact",
      sampling: input.assessment?.distribution?.sampling ?? null,
    },
    chartSpecification: input.chartSpecification,
    capturedBy: input.userId,
    capturedAt: input.capturedAt,
  };
}
