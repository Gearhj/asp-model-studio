import { Fragment, useEffect, useMemo, useRef, useState } from "react";
import {
  CheckCircle2,
  ChevronDown,
  CircleAlert,
  Filter,
  Save,
  Search,
  ShieldCheck,
} from "lucide-react";
import {
  AtlasAttentionPanel,
  AtlasDataScopeBadge,
} from "./ui/AtlasWorkflow";
import {
  assertSpecialValueReviewContract,
  bureauDraftMatchesContract,
  fetchBureauDetection,
  fetchSpecialValueReview,
  loadBureauReviewState,
  saveBureauReviewState,
  specialValueDraftAuthority,
  updateSpecialValueReview,
  SpecialValueReviewApiError,
  type BureauDeclaration,
  type BureauDetectionResponse,
  type BureauDetectionVariable,
  type BureauHandling,
  type BureauReviewDecision,
  type BureauReviewState,
  type BureauVariableDefault,
  type SpecialValueReviewContract,
  type SpecialValueReviewLineage,
  type SpecialValueReviewVariableDecision,
} from "../lib/bureauDetection";
import {
  fetchBureauSemanticAnnotations,
  type BureauSemanticAnnotation,
  type BureauSemanticAnnotationContract,
} from "../lib/bureauSemanticAnnotations";
import { createEvidence, getEvidence } from "../lib/evidenceGraph";
import {
  buildCanonicalEvidenceEnvelope,
  type CanonicalDatasetIdentity,
} from "../lib/datasetIdentity";
import { logDecision } from "../lib/decisionJournal";
import { projectWorkflowRoute } from "../lib/projectScopedRoutes";
import { useWorkflowStore } from "../state/useWorkflowStore";

const handlingLabels: Record<BureauHandling, string> = {
  preserve_informative: "Leave value unchanged (governed special code)",
  convert_to_missing: "Treat as missing for imputation",
  convert_to_category: "Create special-value indicator (dummy variable)",
  documented_domain_mapping: "Impute with a valid governed value",
  exclude_variable: "Exclude feature from modeling",
  leave_unchanged: "Leave value unchanged",
  custom: "Custom treatment (requires rationale)",
};

const primaryHandlingChoices: BureauHandling[] = [
  "convert_to_category",
  "documented_domain_mapping",
  "exclude_variable",
  "preserve_informative",
];

const handlingHelp: Record<BureauHandling, string> = {
  preserve_informative:
    "Keep the observed special code as-is in the predictor.",
  convert_to_missing:
    "Treat the special code as missing so it can be handled in the Missing Values step.",
  convert_to_category:
    "Create a separate 0/1 indicator that identifies rows with this special-value state.",
  documented_domain_mapping:
    "Replace the special code with a documented value that is valid for this predictor.",
  exclude_variable:
    "Remove this predictor from the modeling feature set.",
  leave_unchanged:
    "Keep the observed special code as-is in the predictor.",
  custom:
    "Record a different governed treatment and explain the rationale.",
};

function selectableHandlingEntries(current?: BureauHandling) {
  const values =
    current && !primaryHandlingChoices.includes(current)
      ? [current, ...primaryHandlingChoices]
      : primaryHandlingChoices;
  return values.map((value) => ({
    value,
    label:
      current === value && !primaryHandlingChoices.includes(value)
        ? `${handlingLabels[value]} (saved policy)`
        : handlingLabels[value],
  }));
}

const destructiveTreatments = new Set<BureauHandling>([
  "convert_to_missing",
  "documented_domain_mapping",
  "exclude_variable",
  "custom",
]);

function catalogMatchPresentation(
  contract: BureauSemanticAnnotationContract | null,
  annotation?: BureauSemanticAnnotation,
) {
  if (!contract) {
    return {
      label: "Checking catalog",
      className: "border-slate-200 bg-slate-50 text-slate-700",
    };
  }
  if (contract.state === "unavailable") {
    return {
      label:
        contract.reason === "not_entitled"
          ? "Catalog unavailable"
          : contract.reason === "service_unavailable"
            ? "Catalog temporarily unavailable"
            : "No catalog binding",
      className: "border-slate-200 bg-slate-50 text-slate-700",
    };
  }
  if (!annotation) {
    return {
      label: "Unverified candidate",
      className: "border-amber-200 bg-amber-50 text-amber-900",
    };
  }
  if (!annotation.providerAuthoritative || !annotation.mappingAccepted) {
    if (annotation.mappingState === "transformed_or_derived") {
      return {
        label: "Derived · non-authoritative",
        className: "border-violet-200 bg-violet-50 text-violet-800",
      };
    }
    if (annotation.mappingState === "rejected") {
      return {
        label: "Candidate rejected",
        className: "border-rose-200 bg-rose-50 text-rose-800",
      };
    }
    return {
      label: "Non-authoritative review",
      className: "border-amber-200 bg-amber-50 text-amber-900",
    };
  }
  if (annotation.mappingState === "exact_verified") {
    return {
      label: "Exact provider match",
      className: "border-emerald-200 bg-emerald-50 text-emerald-800",
    };
  }
  if (annotation.mappingState === "approved_alias") {
    return {
      label: "Approved alias",
      className: "border-blue-200 bg-blue-50 text-blue-800",
    };
  }
  return {
    label: "Review required",
    className: "border-amber-200 bg-amber-50 text-amber-900",
  };
}

function treatmentRequiresRationale(
  handling: BureauHandling,
  override: boolean,
) {
  return override || destructiveTreatments.has(handling);
}

function treatmentRequiresReplacement(handling: BureauHandling) {
  return handling === "documented_domain_mapping";
}

function defaultDecision(
  state: BureauReviewState,
  variable: string,
): BureauVariableDefault {
  return (
    state.variableDefaults.find((row) => row.variable === variable) ?? {
      variable,
      handling: "preserve_informative",
      rationale: "",
      updatedAt: "",
    }
  );
}

function explicitVariableDefault(
  state: BureauReviewState,
  variable: string,
) {
  return (
    state.variableDefaults.find((row) => row.variable === variable) ?? null
  );
}

function valueOverride(
  state: BureauReviewState,
  variable: string,
  value: number,
) {
  return state.decisions.find(
    (row) => row.variable === variable && row.value === value,
  );
}

function reviewStateForVariable(
  state: BureauReviewState,
  variable: BureauDetectionVariable,
) {
  const policy = explicitVariableDefault(state, variable.variable);
  if (!policy) {
    return {
      reviewed: false,
      unresolved: 1,
      handling: null,
    };
  }
  const defaultReady =
    (!treatmentRequiresRationale(policy.handling, false) ||
      !!policy.rationale.trim()) &&
    (!treatmentRequiresReplacement(policy.handling) ||
      !!policy.replacementValue?.trim());
  const unresolvedRows = variable.special_values.filter((profile) => {
    const override = valueOverride(
      state,
      variable.variable,
      profile.value,
    );
    if (!override) return false;
    return (
      (treatmentRequiresRationale(override.handling, true) &&
        !override.rationale.trim()) ||
      (treatmentRequiresReplacement(override.handling) &&
        !override.replacementValue?.trim())
    );
  }).length;
  return {
    reviewed: defaultReady && unresolvedRows === 0,
    unresolved: (defaultReady ? 0 : 1) + unresolvedRows,
    handling: policy.handling,
  };
}

function matchesDurableVariableDecision(
  state: BureauReviewState,
  variable: string,
  durableDecision: SpecialValueReviewVariableDecision | undefined,
) {
  if (!durableDecision) return false;
  const policy = explicitVariableDefault(state, variable);
  if (!policy) return false;
  if (
    policy.handling !== durableDecision.policy ||
    policy.rationale.trim() !== durableDecision.rationale.trim() ||
    (policy.replacementValue ?? "").trim() !==
      String(durableDecision.replacement_value ?? "").trim()
  ) {
    return false;
  }
  const draftOverrides = state.decisions
    .filter((decision) => decision.variable === variable)
    .map((decision) => ({
      value: Number(decision.value),
      policy: decision.handling,
      rationale: decision.rationale.trim(),
      replacement_value: (decision.replacementValue ?? "").trim(),
    }))
    .sort((left, right) => left.value - right.value);
  const durableOverrides = durableDecision.overrides
    .map((override) => ({
      value: Number(override.value),
      policy: override.policy,
      rationale: override.rationale.trim(),
      replacement_value: String(override.replacement_value ?? "").trim(),
    }))
    .sort((left, right) => left.value - right.value);
  return JSON.stringify(draftOverrides) === JSON.stringify(durableOverrides);
}

function pct(value: number | null | undefined, digits = 2) {
  return typeof value === "number" && Number.isFinite(value)
    ? `${(value * 100).toFixed(digits)}%`
    : "Not available";
}

function largestEventRateDifference(variable: BureauDetectionVariable) {
  const deltas = variable.special_values
    .map((profile) => profile.event_rate_delta)
    .filter((value): value is number =>
      typeof value === "number" && Number.isFinite(value),
    );
  if (!deltas.length) return null;
  return deltas.reduce((largest, value) =>
    Math.abs(value) > Math.abs(largest) ? value : largest,
  );
}

function recommendedFeatureTreatment(variable: BureauDetectionVariable) {
  const recommendations = Array.from(
    new Set(
      variable.special_values
        .map((profile) => profile.recommended_handling.trim())
        .filter(Boolean),
    ),
  );
  if (!recommendations.length) return "No backend recommendation";
  return recommendations.length === 1
    ? recommendations[0]
    : "Feature-specific review required";
}

function variableDomToken(value: string | number) {
  return String(value).replace(/[^A-Za-z0-9_-]/g, "-");
}

function emptyBrowserReviewDraft(): BureauReviewState {
  return {
    declaration: "auto",
    rationale: "",
    decisions: [],
    variableDefaults: [],
    status: "draft",
    evidenceStatus: "not_recorded",
  };
}

export const FOCUS_FIRST_SPECIAL_VALUE_REVIEW_EVENT =
  "atlas-special-value-review:focus-first-unresolved";

type SpecialValueVariableSort =
  | "unresolved_first"
  | "prevalence_desc"
  | "prevalence_asc"
  | "affected_rows_desc"
  | "affected_rows_asc"
  | "special_code_count_desc"
  | "special_code_count_asc"
  | "event_rate_delta_desc"
  | "event_rate_delta_asc"
  | "name";

export type BureauReviewPanelStatus = {
  loading: boolean;
  detected: boolean;
  totalVariables: number;
  reviewedVariables: number;
  unresolvedRequirements: number;
  confirmed: boolean;
  blocking: boolean;
  durableStatus?: SpecialValueReviewContract["status"];
  durableRevision?: number;
  firstUnresolvedVariable?: string;
  error?: boolean;
};

export type BureauReviewPanelResult = {
  detection: BureauDetectionResponse;
  review: SpecialValueReviewContract;
};

function exactReviewLineage(
  result: BureauDetectionResponse,
  datasetIdentity: CanonicalDatasetIdentity,
  projectId: string,
): SpecialValueReviewLineage {
  return {
    projectId,
    datasetIdentity,
    activationRevision: result.activation_revision,
    predictorAuthorizationId: result.predictor_authorization_id,
    targetContractId: result.target_contract_id,
    analysisPartitionId: result.analysis_partition_id,
    analysisPartitionRevision: result.analysis_partition_revision,
  };
}

function stateFromDurableReview(
  previous: BureauReviewState,
  review: SpecialValueReviewContract,
): BureauReviewState {
  const now = review.updated_at ?? new Date().toISOString();
  return {
    ...previous,
    declaration: bureauDraftMatchesContract(previous, review)
      ? previous.declaration
      : "auto",
    rationale: review.reviewer_rationale,
    variableDefaults: review.variable_decisions.map((decision) => ({
      variable: decision.variable,
      handling: decision.policy,
      rationale: decision.rationale,
      replacementValue:
        decision.replacement_value == null
          ? undefined
          : String(decision.replacement_value),
      updatedAt: now,
    })),
    decisions: review.variable_decisions.flatMap((decision) =>
      decision.overrides.map((override) => ({
        variable: decision.variable,
        value: Number(override.value),
        handling: override.policy,
        rationale: override.rationale,
        replacementValue:
          override.replacement_value == null
            ? undefined
            : String(override.replacement_value),
        updatedAt: now,
        override: true as const,
      })),
    ),
    status: "draft",
    // Durable review confirmation is not evidence verification. A separate
    // create/read-back round trip is required before this can become ready.
    evidenceStatus:
      previous.evidenceStatus === "not_recorded" ? "not_recorded" : "stale",
    confirmedAt: undefined,
    savedAt: review.updated_at ?? undefined,
    draftAuthority: specialValueDraftAuthority(review),
  };
}

function draftDiffersFromDurableReview(
  state: BureauReviewState,
  review: SpecialValueReviewContract,
  variables: BureauDetectionVariable[],
) {
  if (state.rationale.trim() !== review.reviewer_rationale.trim()) return true;
  const durableByVariable = new Map(
    review.variable_decisions.map(
      (decision) => [decision.variable, decision] as const,
    ),
  );
  return variables.some((variable) => {
    const local = explicitVariableDefault(state, variable.variable);
    const durable = durableByVariable.get(variable.variable);
    if (!local && !durable) return false;
    return !matchesDurableVariableDecision(state, variable.variable, durable);
  });
}

function exactEvidenceReadBack(
  evidence: Awaited<ReturnType<typeof getEvidence>>,
  state: BureauReviewState,
  review: SpecialValueReviewContract,
  identity: CanonicalDatasetIdentity,
) {
  const lineage = (evidence.lineage ?? {}) as Record<string, unknown>;
  const payload = (evidence.payload ?? {}) as Record<string, unknown>;
  const expectedStatus =
    review.status === "confirmed" || review.status === "not_required"
      ? "ready"
      : "draft";
  return (
    evidence.evidenceId === state.evidenceId &&
    evidence.status === expectedStatus &&
    String(evidence.project_id ?? lineage.project_id ?? "") ===
      identity.project_id &&
    String(evidence.dataset_id ?? lineage.dataset_id ?? "") ===
      identity.dataset_id &&
    String(
      evidence.dataset_version_id ?? lineage.dataset_version_id ?? "",
    ) === identity.dataset_version_id &&
    String(payload.durableReviewId ?? "") ===
      review.special_value_review_id &&
    Number(payload.durableRevision) === review.revision &&
    (payload.analysisPartitionId == null
      ? null
      : String(payload.analysisPartitionId)) ===
      review.analysis_partition_id &&
    (payload.analysisPartitionRevision == null
      ? null
      : Number(payload.analysisPartitionRevision)) ===
      review.analysis_partition_revision
  );
}

async function verifyCachedEvidence(
  state: BureauReviewState,
  review: SpecialValueReviewContract,
  identity: CanonicalDatasetIdentity,
) {
  const stale = {
    ...state,
    evidenceStatus:
      state.evidenceStatus === "not_recorded"
        ? ("not_recorded" as const)
        : ("stale" as const),
  };
  if (
    !bureauDraftMatchesContract(state, review) ||
    !state.evidenceId ||
    state.evidenceReviewRevision !== review.revision
  ) {
    return stale;
  }
  try {
    const evidence = await getEvidence(state.evidenceId);
    if (!exactEvidenceReadBack(evidence, state, review, identity)) return stale;
    return {
      ...state,
      evidenceStatus:
        review.status === "confirmed" || review.status === "not_required"
          ? ("ready" as const)
          : ("draft" as const),
    };
  } catch {
    return stale;
  }
}

export default function BureauReviewPanel({
  target,
  eventValue,
  enabled,
  datasetIdentity,
  onReviewStatus,
  onReviewResult,
}: {
  target: string;
  eventValue: unknown;
  enabled: boolean;
  datasetIdentity: CanonicalDatasetIdentity | null;
  onReviewStatus?: (status: BureauReviewPanelStatus) => void;
  onReviewResult?: (result: BureauReviewPanelResult | null) => void;
}) {
  const projectId = useWorkflowStore((state) => state.projectId);
  const projectName = useWorkflowStore((state) => state.projectName);
  const [state, setState] = useState<BureauReviewState>(() =>
    projectId ? loadBureauReviewState(projectId) : emptyBrowserReviewDraft(),
  );
  const [result, setResult] = useState<BureauDetectionResponse | null>(null);
  const [durableReview, setDurableReview] =
    useState<SpecialValueReviewContract | null>(null);
  const [semanticAnnotations, setSemanticAnnotations] =
    useState<BureauSemanticAnnotationContract | null>(null);
  const [draftDirty, setDraftDirty] = useState(false);
  const [selectedVariable, setSelectedVariable] = useState("");
  const [variableSearch, setVariableSearch] = useState("");
  const [reviewFilter, setReviewFilter] = useState<
    "all" | "reviewed" | "unreviewed" | "unresolved"
  >("all");
  const [treatmentFilter, setTreatmentFilter] = useState<
    "all" | BureauHandling
  >("all");
  const [variableSort, setVariableSort] =
    useState<SpecialValueVariableSort>("unresolved_first");
  const [bulkHandling, setBulkHandling] = useState<"" | BureauHandling>("");
  const [bulkReplacementValue, setBulkReplacementValue] = useState("");
  const [treatmentWorkspaceOpen, setTreatmentWorkspaceOpen] = useState(false);
  const [loading, setLoading] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  const [evidenceWarning, setEvidenceWarning] = useState("");
  const [message, setMessage] = useState("");
  const validatedDetectionContextRef = useRef("");

  async function runDetection(signal?: AbortSignal) {
    if (!enabled) {
      setResult(null);
      setDurableReview(null);
      setSemanticAnnotations(null);
      return;
    }
    if (!datasetIdentity || !projectId) {
      setResult(null);
      setSemanticAnnotations(null);
      setError(
        "Credit bureau detection requires the exact active project and Dataset Library version. Reload Data Acquisition and retry.",
      );
      return;
    }
    setLoading(true);
    setError("");
    setEvidenceWarning("");
    setResult(null);
    setDurableReview(null);
    setSemanticAnnotations(null);
    try {
      const scopedDraft = loadBureauReviewState(projectId);
      const detectionContext = [
        projectId,
        datasetIdentity.dataset_id,
        datasetIdentity.dataset_version_id,
        datasetIdentity.activation_revision ?? "current",
        target,
        String(eventValue ?? ""),
      ].join(":");
      const detectionState =
        validatedDetectionContextRef.current === detectionContext
          ? state
          : emptyBrowserReviewDraft();
      const payload = await fetchBureauDetection({
        projectId,
        datasetIdentity,
        target,
        eventValue,
        state: detectionState,
        signal,
      });
      const lineage = exactReviewLineage(payload, datasetIdentity, projectId);
      assertSpecialValueReviewContract(payload.special_value_review, lineage);
      const annotationContractPromise = fetchBureauSemanticAnnotations({
        projectId,
        datasetIdentity,
        signal,
      }).catch((cause): BureauSemanticAnnotationContract | null => {
        if (cause instanceof DOMException && cause.name === "AbortError") {
          return null;
        }
        return {
          state: "unavailable",
          authoritative: false,
          reason: "service_unavailable",
          annotations: [],
        };
      });
      const exactReview = await fetchSpecialValueReview({ lineage, signal });
      if (signal?.aborted) return;
      let hydratedState = stateFromDurableReview(detectionState, exactReview);
      let hasUnsavedDraft = false;
      if (bureauDraftMatchesContract(scopedDraft, exactReview)) {
        hydratedState = await verifyCachedEvidence(
          scopedDraft,
          exactReview,
          datasetIdentity,
        );
        hasUnsavedDraft = draftDiffersFromDurableReview(
          hydratedState,
          exactReview,
          payload.variables.filter(
            (row) => row.likely_bureau && row.special_values.length,
          ),
        );
      }
      if (signal?.aborted) return;
      validatedDetectionContextRef.current = detectionContext;
      setResult(payload);
      setDurableReview(exactReview);
      setTreatmentWorkspaceOpen(exactReview.status !== "confirmed");
      setState(hydratedState);
      saveBureauReviewState(hydratedState, projectId);
      setEvidenceWarning(
        (exactReview.status === "confirmed" ||
          exactReview.status === "not_required") &&
          hydratedState.evidenceStatus !== "ready"
          ? `Supporting evidence is ${hydratedState.evidenceStatus.replace(/_/g, " ")} for durable review revision ${exactReview.revision}. Retry the exact evidence write and read-back without changing the governed review.`
          : "",
      );
      setDraftDirty(hasUnsavedDraft);
      void annotationContractPromise.then((annotationContract) => {
        if (!signal?.aborted && annotationContract) {
          setSemanticAnnotations(annotationContract);
        }
      });
    } catch (cause) {
      if (cause instanceof DOMException && cause.name === "AbortError") return;
      setError(
        cause instanceof Error
          ? cause.message
          : "Credit bureau detection failed.",
      );
      setResult(null);
      setDurableReview(null);
      setSemanticAnnotations(null);
    } finally {
      if (!signal?.aborted) setLoading(false);
    }
  }

  useEffect(() => {
    const controller = new AbortController();
    void runDetection(controller.signal);
    return () => controller.abort();
    // Detection inputs do not include the local treatment draft.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [
    enabled,
    projectId,
    target,
    eventValue,
    state.declaration,
    datasetIdentity?.dataset_id,
    datasetIdentity?.dataset_version_id,
    datasetIdentity?.activation_revision,
  ]);

  useEffect(() => {
    onReviewResult?.(
      result && durableReview ? { detection: result, review: durableReview } : null,
    );
  }, [durableReview, onReviewResult, result]);

  useEffect(() => {
    if (
      new URLSearchParams(window.location.search).get("section") ===
      "credit-bureau-review"
    ) {
      window.setTimeout(
        () =>
          document
            .getElementById("credit-bureau-review")
            ?.scrollIntoView({ behavior: "smooth", block: "start" }),
        250,
      );
    }
  }, []);

  const likelyVariables = useMemo(
    () =>
      result?.variables.filter(
        (row) => row.likely_bureau && row.special_values.length,
      ) ?? [],
    [result],
  );

  const semanticAnnotationByField = useMemo(
    () =>
      new Map(
        semanticAnnotations?.state === "available"
          ? semanticAnnotations.annotations.map((annotation) => [
              annotation.datasetField,
              annotation,
            ] as const)
          : [],
      ),
    [semanticAnnotations],
  );

  useEffect(() => {
    if (
      selectedVariable &&
      !likelyVariables.some((row) => row.variable === selectedVariable)
    ) {
      setSelectedVariable("");
    }
  }, [likelyVariables, selectedVariable]);

  const reviewByVariable = useMemo(
    () => {
      const durableDecisions = new Map<
        string,
        SpecialValueReviewVariableDecision
      >(
        durableReview?.variable_decisions.map((decision) => [
          decision.variable,
          decision,
        ] as const) ?? [],
      );
      return new Map(
        likelyVariables.map((variable) => [
          variable.variable,
          {
            ...reviewStateForVariable(state, variable),
            reviewed: matchesDurableVariableDecision(
              state,
              variable.variable,
              durableDecisions.get(variable.variable),
            ),
          },
        ] as const),
      );
    },
    [durableReview?.variable_decisions, likelyVariables, state],
  );

  const filteredVariables = useMemo(() => {
    const normalized = variableSearch.trim().toLowerCase();
    return likelyVariables
      .filter(
        (variable) =>
          !normalized ||
          `${variable.variable} ${variable.reasons.join(" ")} ${variable.special_values
            .map((profile) => `${profile.value} ${profile.definition}`)
            .join(" ")}`
            .toLowerCase()
            .includes(normalized),
      )
      .filter((variable) => {
        const review = reviewByVariable.get(variable.variable);
        if (reviewFilter === "reviewed") return review?.reviewed;
        if (reviewFilter === "unreviewed") return !review?.reviewed;
        if (reviewFilter === "unresolved") return !!review?.unresolved;
        return true;
      })
      .filter((variable) => {
        if (treatmentFilter === "all") return true;
        return (
          reviewByVariable.get(variable.variable)?.handling ===
          treatmentFilter
        );
      })
      .sort((left, right) => {
        if (variableSort === "unresolved_first") {
          const leftReview = reviewByVariable.get(left.variable);
          const rightReview = reviewByVariable.get(right.variable);
          const leftOpen =
            !!leftReview?.unresolved || !leftReview?.reviewed ? 0 : 1;
          const rightOpen =
            !!rightReview?.unresolved || !rightReview?.reviewed ? 0 : 1;
          return (
            leftOpen - rightOpen ||
            right.special_value_frequency - left.special_value_frequency ||
            left.variable.localeCompare(right.variable)
          );
        }
        if (variableSort === "name") {
          return left.variable.localeCompare(right.variable);
        }
        if (variableSort.startsWith("affected_rows_")) {
          const direction = variableSort.endsWith("_desc") ? -1 : 1;
          return (
            direction *
              (left.special_value_count - right.special_value_count) ||
            left.variable.localeCompare(right.variable)
          );
        }
        if (variableSort.startsWith("special_code_count_")) {
          const direction = variableSort.endsWith("_desc") ? -1 : 1;
          return (
            direction *
              (left.special_values.length - right.special_values.length) ||
            left.variable.localeCompare(right.variable)
          );
        }
        if (variableSort.startsWith("event_rate_delta_")) {
          const direction = variableSort.endsWith("_desc") ? -1 : 1;
          const leftValue = largestEventRateDifference(left);
          const rightValue = largestEventRateDifference(right);
          if (leftValue == null && rightValue != null) return 1;
          if (leftValue != null && rightValue == null) return -1;
          const leftDelta = Math.abs(leftValue ?? 0);
          const rightDelta = Math.abs(rightValue ?? 0);
          return (
            direction * (leftDelta - rightDelta) ||
            left.variable.localeCompare(right.variable)
          );
        }
        const direction = variableSort === "prevalence_desc" ? -1 : 1;
        return (
          direction *
            (left.special_value_frequency -
              right.special_value_frequency) ||
          left.variable.localeCompare(right.variable)
        );
      });
  }, [
    likelyVariables,
    reviewByVariable,
    reviewFilter,
    treatmentFilter,
    variableSearch,
    variableSort,
  ]);

  const activeVariable =
    likelyVariables.find((row) => row.variable === selectedVariable) ?? null;

  const draftUnresolvedCount = useMemo(
    () =>
      likelyVariables.reduce(
        (total, variable) =>
          total +
          (reviewByVariable.get(variable.variable)?.unresolved ?? 0),
        0,
      ),
    [likelyVariables, reviewByVariable],
  );
  const reviewedCount = durableReview?.reviewed_count ?? 0;
  const unresolvedCount = durableReview?.open_count ?? likelyVariables.length;
  const durableOpenVariables = useMemo(
    () => new Set(durableReview?.open_items ?? []),
    [durableReview?.open_items],
  );
  const bulkEligibleVariables = useMemo(
    () =>
      filteredVariables.filter(
        (variable) =>
          durableOpenVariables.has(variable.variable) &&
          !explicitVariableDefault(state, variable.variable) &&
          !state.decisions.some(
            (decision) => decision.variable === variable.variable,
          ),
      ),
    [durableOpenVariables, filteredVariables, state],
  );
  const unresolvedFilteredCount = bulkEligibleVariables.length;
  const firstUnresolvedVariable = useMemo(
    () =>
      [...likelyVariables]
        .filter((variable) => {
          const review = reviewByVariable.get(variable.variable);
          return !!review?.unresolved || !review?.reviewed;
        })
        .sort(
          (left, right) =>
            (reviewByVariable.get(right.variable)?.unresolved ?? 0) -
              (reviewByVariable.get(left.variable)?.unresolved ?? 0) ||
            right.special_value_frequency - left.special_value_frequency ||
            left.variable.localeCompare(right.variable),
        )[0]?.variable,
    [likelyVariables, reviewByVariable],
  );

  function revealFirstUnresolved() {
    if (!firstUnresolvedVariable) return;
    const variable = likelyVariables.find(
      (row) => row.variable === firstUnresolvedVariable,
    );
    if (!variable) return;
    setVariableSearch("");
    setReviewFilter("all");
    setTreatmentFilter("all");
    setVariableSort("unresolved_first");
    setTreatmentWorkspaceOpen(true);
    setSelectedVariable(variable.variable);
    const token = variableDomToken(variable.variable);
    const policy = explicitVariableDefault(state, variable.variable);
    let focusId = `special-value-treatment-${token}`;
    if (
      policy &&
      treatmentRequiresReplacement(policy.handling) &&
      !policy.replacementValue?.trim()
    ) {
      focusId = `special-value-replacement-${token}`;
    } else if (
      policy &&
      treatmentRequiresRationale(policy.handling, false) &&
      !policy.rationale.trim()
    ) {
      focusId = `special-value-rationale-${token}`;
    } else {
      const unresolvedOverride = variable.special_values.find((profile) => {
        const override = valueOverride(
          state,
          variable.variable,
          profile.value,
        );
        return Boolean(
          override &&
            ((treatmentRequiresReplacement(override.handling) &&
              !override.replacementValue?.trim()) ||
              !override.rationale.trim()),
        );
      });
      if (unresolvedOverride) {
        const override = valueOverride(
          state,
          variable.variable,
          unresolvedOverride.value,
        );
        focusId =
          override &&
          treatmentRequiresReplacement(override.handling) &&
          !override.replacementValue?.trim()
            ? `special-value-override-replacement-${token}-${variableDomToken(unresolvedOverride.value)}`
            : `special-value-override-rationale-${token}-${variableDomToken(unresolvedOverride.value)}`;
      }
    }
    window.setTimeout(() => {
      const row = document.getElementById(`special-value-feature-row-${token}`);
      row?.scrollIntoView({ behavior: "smooth", block: "center" });
      const control = document.getElementById(focusId) as HTMLElement | null;
      control?.focus({ preventScroll: true });
    }, 50);
  }

  useEffect(() => {
    const handleFocusRequest = () => revealFirstUnresolved();
    window.addEventListener(
      FOCUS_FIRST_SPECIAL_VALUE_REVIEW_EVENT,
      handleFocusRequest,
    );
    return () =>
      window.removeEventListener(
        FOCUS_FIRST_SPECIAL_VALUE_REVIEW_EVENT,
        handleFocusRequest,
      );
  });
  const treatmentCounts = useMemo(() => {
    const counts = new Map<BureauHandling, number>();
    likelyVariables.forEach((variable) => {
      const handling = explicitVariableDefault(
        state,
        variable.variable,
      )?.handling;
      if (!handling) return;
      counts.set(handling, (counts.get(handling) ?? 0) + 1);
    });
    return [...counts.entries()].sort((left, right) => right[1] - left[1]);
  }, [likelyVariables, state]);
  const totalOverrideCount = useMemo(
    () =>
      state.decisions.filter((decision) =>
        likelyVariables.some(
          (variable) => variable.variable === decision.variable,
        ),
      ).length,
    [likelyVariables, state.decisions],
  );
  const reviewState = draftDirty
    ? "Unsaved draft"
    : durableReview?.status === "confirmed"
      ? "Confirmed"
      : durableReview?.status === "not_required"
        ? "Not required"
        : durableReview?.status === "ready_for_confirmation"
          ? "Ready to confirm"
          : durableReview?.status === "in_review"
            ? "In review"
            : "Not started";
  const confirmedAndClean = Boolean(
    durableReview?.status === "confirmed" &&
      durableReview.open_count === 0 &&
      !draftDirty,
  );

  useEffect(() => {
    onReviewStatus?.({
      loading,
      detected: Boolean(durableReview && durableReview.detected_count > 0),
      totalVariables: durableReview?.detected_count ?? likelyVariables.length,
      reviewedVariables: reviewedCount,
      unresolvedRequirements: unresolvedCount,
      confirmed: Boolean(
        durableReview?.status === "confirmed" &&
          durableReview.open_count === 0 &&
          !draftDirty,
      ),
      blocking: Boolean(
        loading ||
          error ||
          !durableReview ||
          draftDirty ||
          durableReview.blocks_continuation,
      ),
      durableStatus: durableReview?.status,
      durableRevision: durableReview?.revision,
      firstUnresolvedVariable,
      error: Boolean(error),
    });
  }, [
    draftDirty,
    durableReview,
    error,
    firstUnresolvedVariable,
    likelyVariables.length,
    loading,
    onReviewStatus,
    reviewedCount,
    unresolvedCount,
  ]);

  function updateState(next: BureauReviewState) {
    const draft: BureauReviewState = {
      ...next,
      status: "draft",
      evidenceStatus:
        next.evidenceStatus === "not_recorded"
          ? "not_recorded"
          : "stale",
      confirmedAt: undefined,
      draftAuthority: durableReview
        ? specialValueDraftAuthority(durableReview)
        : next.draftAuthority,
    };
    setState(draft);
    saveBureauReviewState(draft, projectId);
    setDraftDirty(true);
    setMessage("");
  }

  function updateVariableDefault(
    variable: string,
    patch: Partial<BureauVariableDefault>,
  ) {
    const existing = defaultDecision(state, variable);
    const nextDefault: BureauVariableDefault = {
      ...existing,
      ...patch,
      variable,
      replacementValue:
        patch.replacementValue !== undefined
          ? patch.replacementValue
          : patch.handling && patch.handling !== existing.handling
            ? undefined
            : existing.replacementValue,
      updatedAt: new Date().toISOString(),
    };
    updateState({
      ...state,
      variableDefaults: [
        nextDefault,
        ...state.variableDefaults.filter(
          (row) => row.variable !== variable,
        ),
      ],
    });
    logDecision({
      workflowStep: "Data Acquisition",
      actionType: "workflow_setting_changed",
      subject: `${variable} bureau special-value default`,
      previousValue: existing.handling,
      newValue: nextDefault.handling,
      systemRecommendation:
        "Apply one governed variable-level policy, then document only destructive choices and true value-level overrides.",
      userReason: nextDefault.rationale,
    });
  }

  function applyBulkTreatment() {
    const unresolvedVariables = bulkEligibleVariables;
    if (!bulkHandling || !unresolvedVariables.length) return;
    if (
      treatmentRequiresReplacement(bulkHandling) &&
      !bulkReplacementValue.trim()
    ) {
      setMessage(
        "Enter the governed replacement value before applying this imputation treatment.",
      );
      return;
    }
    const variables = new Set(
      unresolvedVariables.map((variable) => variable.variable),
    );
    const now = new Date().toISOString();
    const replacements = unresolvedVariables.map((variable) => {
      const existing = defaultDecision(state, variable.variable);
      return {
        ...existing,
        handling: bulkHandling,
        replacementValue: treatmentRequiresReplacement(bulkHandling)
          ? bulkReplacementValue.trim()
          : undefined,
        rationale:
          existing.handling === bulkHandling ? existing.rationale : "",
        updatedAt: now,
      } satisfies BureauVariableDefault;
    });
    updateState({
      ...state,
      variableDefaults: [
        ...replacements,
        ...state.variableDefaults.filter(
          (row) => !variables.has(row.variable),
        ),
      ],
    });
    if (treatmentRequiresRationale(bulkHandling, false)) {
      setSelectedVariable(unresolvedVariables[0]?.variable ?? "");
    }
    setMessage(
      `${handlingLabels[bulkHandling]} applied to ${unresolvedVariables.length.toLocaleString()} unresolved filtered attribute${unresolvedVariables.length === 1 ? "" : "s"} in this browser draft. Save Draft Review or confirm explicitly to make it durable.`,
    );
    logDecision({
      workflowStep: "Data Acquisition",
      actionType: "workflow_setting_changed",
      subject: `${unresolvedVariables.length} unresolved special-value feature treatments`,
      previousValue: "Mixed feature-level policies",
      newValue: bulkHandling,
      systemRecommendation:
        "Bulk changes remain a browser draft until the reviewer explicitly saves or confirms the complete governed treatment contract.",
      userReason: state.rationale,
    });
  }

  function updateOverride(
    variable: string,
    value: number,
    handling: "" | BureauHandling,
  ) {
    const existing = valueOverride(state, variable, value);
    if (!handling) {
      updateState({
        ...state,
        decisions: state.decisions.filter(
          (row) => !(row.variable === variable && row.value === value),
        ),
      });
      return;
    }
    const nextDecision: BureauReviewDecision = {
      variable,
      value,
      handling,
      rationale: existing?.rationale ?? "",
      replacementValue:
        existing?.handling === handling
          ? existing.replacementValue
          : undefined,
      updatedAt: new Date().toISOString(),
      override: true,
    };
    updateState({
      ...state,
      decisions: [
        nextDecision,
        ...state.decisions.filter(
          (row) => !(row.variable === variable && row.value === value),
        ),
      ],
    });
    logDecision({
      workflowStep: "Data Acquisition",
      actionType: "workflow_setting_changed",
      subject: `${variable} bureau special value ${value}`,
      previousValue:
        existing?.handling ??
        explicitVariableDefault(state, variable)?.handling ??
        "No feature-level treatment selected",
      newValue: nextDecision.handling,
      systemRecommendation:
        "A value-level override requires rationale because it departs from the governed variable default.",
      userReason: nextDecision.rationale,
    });
  }

  function updateOverrideRationale(
    variable: string,
    value: number,
    rationale: string,
  ) {
    const existing = valueOverride(state, variable, value);
    if (!existing) return;
    updateState({
      ...state,
      decisions: [
        {
          ...existing,
          rationale,
          updatedAt: new Date().toISOString(),
        },
        ...state.decisions.filter(
          (row) => !(row.variable === variable && row.value === value),
        ),
      ],
    });
  }

  function updateOverrideReplacement(
    variable: string,
    value: number,
    replacementValue: string,
  ) {
    const existing = valueOverride(state, variable, value);
    if (!existing) return;
    updateState({
      ...state,
      decisions: [
        {
          ...existing,
          replacementValue,
          updatedAt: new Date().toISOString(),
        },
        ...state.decisions.filter(
          (row) => !(row.variable === variable && row.value === value),
        ),
      ],
    });
  }

  async function createAndVerifySupportingEvidence(
    review: SpecialValueReviewContract,
    reviewState: BureauReviewState,
  ) {
    if (!result || !datasetIdentity) {
      throw new Error(
        "Supporting evidence requires the exact active Dataset Library version and current detection result.",
      );
    }
    const createdEvidence = await createEvidence({
      ...buildCanonicalEvidenceEnvelope(datasetIdentity, {
        scope: result.scope,
        rowCount: result.row_count,
        target: result.target,
        metadataSource: result.metadata_source,
      }),
      projectName,
      evidenceType: "dataset",
      title: "Credit Bureau Detection and Special-Value Review",
      summary: result.detected
        ? `${result.likely_variable_count} bureau variables and ${result.rows_with_special_values.toLocaleString()} special-value-bearing rows were reviewed using governed full-population evidence.`
        : "No credit bureau data was confirmed after automated and manual review.",
      sourcePage: "Data Acquisition",
      sourceRoute: `${projectWorkflowRoute(projectId, "/step01")}?section=credit-bureau-review`,
      modelIds: [],
      documentIds: [],
      notebookIds: [],
      supportsSections: ["Data Sources", "Data Quality", "Feature Engineering"],
      tags: ["predictive_modeling", "bureau_review", "special_values"],
      status:
        review.status === "confirmed" || review.status === "not_required"
          ? "ready"
          : "draft",
      importance: "high",
      payload: {
        detected: result.detected,
        confidence: result.confidence,
        reasons: result.reasons,
        variables: result.variables,
        rowsWithSpecialValues: result.rows_with_special_values,
        declaration: reviewState.declaration,
        variableDefaults: reviewState.variableDefaults,
        valueOverrides: reviewState.decisions,
        reviewerRationale: review.reviewer_rationale,
        reviewStatus: review.status,
        durableReviewId: review.special_value_review_id,
        durableRevision: review.revision,
        detectionFingerprint: review.detection_fingerprint,
        activationRevision: review.activation_revision,
        predictorAuthorizationId: review.predictor_authorization_id,
        targetContractId: review.target_contract_id,
        analysisPartitionId: review.analysis_partition_id,
        analysisPartitionRevision: review.analysis_partition_revision,
        reviewer: "Current ATLAS user",
        reviewedAt: result.reviewed_at,
        confirmedAt: review.confirmed_at,
        semanticSeparation: {
          nullMissingValues: "separate",
          parseFailures: "separate",
          ordinaryOutliers: "separate",
        },
      },
    }, { requireDatabaseMirror: true });
    const evidenceCandidate: BureauReviewState = {
      ...reviewState,
      evidenceId: createdEvidence.evidenceId,
      evidenceReviewRevision: review.revision,
      evidenceStatus: "stale",
    };
    const evidenceReadBack = await getEvidence(createdEvidence.evidenceId);
    if (
      !exactEvidenceReadBack(
        evidenceReadBack,
        evidenceCandidate,
        review,
        datasetIdentity,
      )
    ) {
      throw new Error(
        "The persisted evidence could not be read back with the exact review revision and dataset lineage.",
      );
    }
    return {
      ...evidenceCandidate,
      evidenceStatus:
        review.status === "confirmed" || review.status === "not_required"
          ? ("ready" as const)
          : ("draft" as const),
    };
  }

  async function retrySupportingEvidence() {
    if (!durableReview || !result || !datasetIdentity) return;
    setSaving(true);
    setError("");
    setEvidenceWarning("");
    setMessage("Retrying the exact durable review evidence read-back...");
    const reviewState = stateFromDurableReview(state, durableReview);
    try {
      const evidencedState = await createAndVerifySupportingEvidence(
        durableReview,
        reviewState,
      );
      setState(evidencedState);
      saveBureauReviewState(evidencedState, projectId);
      setEvidenceWarning("");
      setMessage(
        `Supporting evidence is current for durable review revision ${durableReview.revision}.`,
      );
    } catch (cause) {
      const staleState: BureauReviewState = {
        ...reviewState,
        evidenceStatus: "stale",
      };
      setState(staleState);
      saveBureauReviewState(staleState, projectId);
      setEvidenceWarning(
        `Supporting evidence remains stale for durable review revision ${durableReview.revision}. ${cause instanceof Error ? cause.message : "Retry evidence creation."}`,
      );
      setMessage(
        "The backend review remains authoritative; supporting evidence can be retried without changing its revision.",
      );
    } finally {
      setSaving(false);
    }
  }

  async function persistReview(mode: "draft" | "confirmed") {
    if (!result || !durableReview) return;
    if (!datasetIdentity) {
      setError(
        "Credit bureau evidence requires an exact active Dataset Library version. Reactivate the registered dataset before saving this review.",
      );
      return;
    }
    if (mode === "confirmed" && draftUnresolvedCount) {
      setError(
        `${draftUnresolvedCount} treatment requirement${draftUnresolvedCount === 1 ? "" : "s"} remain unresolved. Add the indicated rationale before confirmation.`,
      );
      return;
    }
    setSaving(true);
    setError("");
    setEvidenceWarning("");
    setMessage(
      mode === "confirmed"
        ? "Confirming the governed special-value treatment..."
        : "Saving the draft special-value review...",
    );
    const lineage = exactReviewLineage(result, datasetIdentity, projectId);
    const variableDecisions: SpecialValueReviewVariableDecision[] =
      likelyVariables.flatMap((variable) => {
        const policy = explicitVariableDefault(state, variable.variable);
        if (!policy) return [];
        return [{
          variable: variable.variable,
          policy: policy.handling,
          rationale: policy.rationale.trim(),
          replacement_value: treatmentRequiresReplacement(policy.handling)
            ? policy.replacementValue?.trim()
            : undefined,
          overrides: state.decisions
            .filter((decision) => decision.variable === variable.variable)
            .map((decision) => ({
              value: decision.value,
              policy: decision.handling,
              rationale: decision.rationale.trim(),
              replacement_value: treatmentRequiresReplacement(
                decision.handling,
              )
                ? decision.replacementValue?.trim()
                : undefined,
            })),
        }];
      });
    let savedReview: SpecialValueReviewContract;
    try {
      savedReview = await updateSpecialValueReview({
        lineage,
        current: durableReview,
        intent: mode === "confirmed" ? "confirm" : "draft",
        variableDecisions,
        reviewerRationale: state.rationale.trim(),
      });
      const nextState = stateFromDurableReview(state, savedReview);
      setDurableReview(savedReview);
      setState(nextState);
      saveBureauReviewState(nextState, projectId);
      setDraftDirty(false);
      setTreatmentWorkspaceOpen(savedReview.status !== "confirmed");
    } catch (cause) {
      if (cause instanceof SpecialValueReviewApiError && cause.currentReview) {
        try {
          setDurableReview(
            assertSpecialValueReviewContract(cause.currentReview, lineage),
          );
        } catch {
          // The conflict payload was not current for this exact lineage.
        }
      }
      setError(
        cause instanceof Error
          ? cause.message
          : "The durable special-value review could not be saved.",
      );
      setMessage("");
      setSaving(false);
      return;
    }

    try {
      const nextState = stateFromDurableReview(state, savedReview);
      const createdEvidence = await createEvidence({
        ...buildCanonicalEvidenceEnvelope(datasetIdentity, {
          scope: result.scope,
          rowCount: result.row_count,
          target: result.target,
          metadataSource: result.metadata_source,
        }),
        projectName,
        evidenceType: "dataset",
        title: "Credit Bureau Detection and Special-Value Review",
        summary: result.detected
          ? `${result.likely_variable_count} bureau variables and ${result.rows_with_special_values.toLocaleString()} special-value-bearing rows were reviewed using governed full-population evidence.`
          : "No credit bureau data was confirmed after automated and manual review.",
        sourcePage: "Data Acquisition",
        sourceRoute: `${projectWorkflowRoute(projectId, "/step01")}?section=credit-bureau-review`,
        modelIds: [],
        documentIds: [],
        notebookIds: [],
        supportsSections: [
          "Data Sources",
          "Data Quality",
          "Feature Engineering",
        ],
        tags: [
          "predictive_modeling",
          "bureau_review",
          "special_values",
        ],
        status:
          savedReview.status === "confirmed" ||
          savedReview.status === "not_required"
            ? "ready"
            : "draft",
        importance: "high",
        payload: {
          detected: result.detected,
          confidence: result.confidence,
          reasons: result.reasons,
          variables: result.variables,
          rowsWithSpecialValues: result.rows_with_special_values,
          declaration: nextState.declaration,
          variableDefaults: nextState.variableDefaults,
          valueOverrides: nextState.decisions,
          reviewerRationale: savedReview.reviewer_rationale,
          reviewStatus: savedReview.status,
          durableReviewId: savedReview.special_value_review_id,
          durableRevision: savedReview.revision,
          detectionFingerprint: savedReview.detection_fingerprint,
          activationRevision: savedReview.activation_revision,
          predictorAuthorizationId:
            savedReview.predictor_authorization_id,
          targetContractId: savedReview.target_contract_id,
          analysisPartitionId: savedReview.analysis_partition_id,
          analysisPartitionRevision: savedReview.analysis_partition_revision,
          reviewer: "Current ATLAS user",
          reviewedAt: result.reviewed_at,
          confirmedAt: savedReview.confirmed_at,
          semanticSeparation: {
            nullMissingValues: "separate",
            parseFailures: "separate",
            ordinaryOutliers: "separate",
          },
        },
      }, { requireDatabaseMirror: true });
      const evidenceCandidate: BureauReviewState = {
        ...nextState,
        evidenceId: createdEvidence.evidenceId,
        evidenceReviewRevision: savedReview.revision,
        evidenceStatus: "stale",
      };
      const evidenceReadBack = await getEvidence(createdEvidence.evidenceId);
      if (
        !exactEvidenceReadBack(
          evidenceReadBack,
          evidenceCandidate,
          savedReview,
          datasetIdentity,
        )
      ) {
        throw new Error(
          "The persisted evidence could not be read back with the exact review revision and dataset lineage.",
        );
      }
      const evidencedState: BureauReviewState = {
        ...evidenceCandidate,
        evidenceStatus:
          savedReview.status === "confirmed" ||
          savedReview.status === "not_required"
            ? "ready"
            : "draft",
      };
      setState(evidencedState);
      saveBureauReviewState(evidencedState, projectId);
      setMessage(
        savedReview.status === "confirmed"
          ? `Special-value treatment confirmed durably at revision ${savedReview.revision}; supporting evidence is current.`
          : savedReview.status === "not_required"
            ? `No special-value review is required. Durable revision ${savedReview.revision} is current.`
            : `Draft review saved durably at revision ${savedReview.revision}. Evidence remains draft until confirmation.`,
      );
      logDecision({
        workflowStep: "Data Acquisition",
        actionType: "workflow_setting_changed",
        subject: "Special-Value Treatment Review",
        previousValue: durableReview.status,
        newValue: savedReview.status,
        systemRecommendation:
          "Preserve bureau special-value semantics unless a documented governed treatment requires a change.",
        followStatus:
          savedReview.status === "confirmed" ? "followed" : "not_applicable",
        userReason: state.rationale,
      });
    } catch (cause) {
      const staleState: BureauReviewState = {
        ...stateFromDurableReview(state, savedReview),
        evidenceStatus: "stale",
      };
      setState(staleState);
      saveBureauReviewState(staleState, projectId);
      setEvidenceWarning(
        `Durable special-value review revision ${savedReview.revision} was saved, but supporting evidence could not be updated. ${cause instanceof Error ? cause.message : "Retry evidence creation."}`,
      );
      setMessage(
        `The backend review remains authoritative at revision ${savedReview.revision}; supporting evidence can be retried without changing that revision.`,
      );
    } finally {
      setSaving(false);
    }
  }

  if (!enabled) return null;

  return (
    <section id="credit-bureau-review" className="scroll-mt-24">
      <div
        className="overflow-hidden rounded-xl border-2 border-indigo-800 bg-indigo-50/50 shadow-[0_16px_36px_rgba(30,41,99,0.14)]"
        data-testid="special-value-decision-workspace"
      >
        <div className="flex items-center justify-between gap-3 bg-gradient-to-r from-slate-950 via-indigo-950 to-indigo-900 px-5 py-4 text-white">
          <span className="flex min-w-0 items-center gap-3">
            <span className="rounded-lg border border-violet-300/40 bg-violet-400/15 p-2 text-violet-100">
              <ShieldCheck size={18} />
            </span>
            <span>
              <span className="block text-[10px] font-bold uppercase tracking-[0.18em] text-violet-200">
                Credit Bureau and Special Values
              </span>
              <span className="mt-1 block text-base font-semibold text-white">
                Special-Value Treatment Review
              </span>
              <span className="mt-1 block text-xs text-indigo-100">
                {loading
                  ? "Analyzing full-population bureau signals"
                  : result
                    ? result.detected
                      ? `${result.likely_variable_count} bureau variables · ${reviewedCount} reviewed · ${unresolvedCount} unresolved requirements`
                      : "Automatic detection completed; no bureau variables were confirmed"
                    : error
                      ? "Automatic special-value detection requires attention"
                      : "Preparing automatic special-value detection"}
              </span>
            </span>
          </span>
          <span className="flex items-center gap-2">
            {result ? (
              <span className="rounded-full border border-indigo-300/50 bg-white/10 px-3 py-1 text-xs font-semibold text-indigo-50">
                {reviewState}
              </span>
            ) : null}
          </span>
        </div>

        <div className="space-y-4 bg-gradient-to-b from-indigo-50/80 to-white p-5">
          <div className="flex flex-wrap items-center justify-between gap-3 rounded-lg border border-indigo-200 bg-white px-3 py-2">
            <div className="text-xs font-medium text-slate-700">
              Bureau special values remain separate from true nulls, parse failures, and ordinary outliers.
            </div>
            {result ? <AtlasDataScopeBadge scope="full_dataset" rows={result.row_count} /> : null}
          </div>
          <div
            className="rounded-lg border border-blue-200 bg-blue-50 px-3 py-2 text-xs leading-5 text-blue-950"
            data-testid="special-value-metadata-authority"
          >
            The centrally managed Experian Premier catalog is applied automatically only for exact approved mappings. Dataset-observed candidates, including HELOC negative codes, remain visible without a catalog mapping. ATLAS does not invent provider meanings.
          </div>
          <div className="grid gap-3 lg:grid-cols-[minmax(240px,340px)_1fr] lg:items-end">
            <label>
              <span className="atlas-label">Manual declaration</span>
              <select
                className="atlas-input mt-1"
                value={state.declaration}
                onChange={(event) =>
                  updateState({
                    ...state,
                    declaration: event.target.value as BureauDeclaration,
                  })
                }
              >
                <option value="auto">Use multi-signal detection</option>
                <option value="contains">
                  Contains credit bureau variables
                </option>
                <option value="does_not_contain">
                  Does not contain credit bureau variables
                </option>
                <option value="manual_review">
                  Requires manual review
                </option>
              </select>
            </label>
            <label>
              <span className="atlas-label">
                Review-level rationale
              </span>
              <input
                className="atlas-input mt-1"
                value={state.rationale}
                onChange={(event) =>
                  updateState({ ...state, rationale: event.target.value })
                }
                placeholder="Optional source, policy, or review context."
              />
            </label>
          </div>

          {error ? (
            <AtlasAttentionPanel
              title="Bureau review requires attention"
              tone="danger"
            >
              {error}
            </AtlasAttentionPanel>
          ) : null}

          {evidenceWarning ? (
            <AtlasAttentionPanel
              title="Supporting evidence requires attention"
              tone="warning"
            >
              <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
                <span>{evidenceWarning}</span>
                <button
                  type="button"
                  className="atlas-secondary-button shrink-0"
                  disabled={saving}
                  onClick={() => void retrySupportingEvidence()}
                >
                  Retry Evidence
                </button>
              </div>
            </AtlasAttentionPanel>
          ) : null}

          {result ? (
            <>
              <div
                className="grid gap-2 sm:grid-cols-2 xl:grid-cols-6"
                data-testid="special-value-review-summary"
              >
                <Metric
                  label="Bureau variables detected"
                  value={result.likely_variable_count.toLocaleString()}
                />
                <Metric
                  label="With special values"
                  value={result.variables_with_special_values.toLocaleString()}
                />
                <Metric
                  label="Rows containing specials"
                  value={result.rows_with_special_values.toLocaleString()}
                />
                <Metric
                  label="Review status"
                  value={`${reviewState} · ${reviewedCount}/${likelyVariables.length}`}
                  tone={
                    reviewState === "Confirmed"
                      ? "success"
                      : unresolvedCount
                        ? "warning"
                        : "info"
                  }
                />
                <Metric
                  label="Durable revision"
                  value={
                    durableReview
                      ? `${durableReview.revision}`
                      : "Unavailable"
                  }
                  tone={durableReview ? "info" : "warning"}
                />
                <Metric
                  label="Evidence state"
                  value={state.evidenceStatus.replace(/_/g, " ")}
                  tone={
                    state.evidenceStatus === "ready"
                      ? "success"
                      : state.evidenceStatus === "stale"
                        ? "warning"
                        : "neutral"
                  }
                />
              </div>

              <div
                className={`rounded-lg border px-3 py-2 text-xs font-medium ${
                  durableReview
                    ? "border-indigo-200 bg-indigo-50 text-indigo-950"
                    : "border-amber-200 bg-amber-50 text-amber-950"
                }`}
                data-testid="durable-special-value-review-authority"
              >
                {durableReview
                  ? `Backend durable exact-version authority · status ${durableReview.status.replace(/_/g, " ")} · revision ${durableReview.revision}`
                  : "Backend durable exact-version authority is not available; browser draft data cannot satisfy this review."}
              </div>

              {result.reasons.length ? (
                <details className="rounded-lg border border-slate-200 bg-white p-3">
                  <summary className="cursor-pointer text-xs font-semibold uppercase text-slate-600">
                    Detection evidence · {result.reasons.length} signals
                  </summary>
                  <ul className="mt-2 space-y-1 text-sm text-slate-700">
                    {result.reasons.map((reason) => (
                      <li key={reason}>• {reason}</li>
                    ))}
                  </ul>
                </details>
              ) : null}

              {result.detected && likelyVariables.length ? (
                confirmedAndClean && !treatmentWorkspaceOpen ? (
                  <div
                    className="rounded-xl border border-emerald-300 bg-emerald-50 p-4"
                    data-testid="confirmed-special-value-summary"
                  >
                    <div className="flex flex-col gap-3 lg:flex-row lg:items-center lg:justify-between">
                      <div>
                        <div className="flex items-center gap-2 text-sm font-semibold text-emerald-950">
                          <CheckCircle2 size={16} aria-hidden="true" />
                          Special-value treatments confirmed
                        </div>
                        <p className="mt-1 text-xs leading-5 text-emerald-900">
                          {likelyVariables.length.toLocaleString()} affected
                          feature{likelyVariables.length === 1 ? "" : "s"} are
                          governed by durable revision {durableReview?.revision}.
                          No browser draft is pending.
                        </p>
                      </div>
                      <button
                        type="button"
                        className="atlas-secondary-button"
                        data-testid="review-or-change-special-value-treatments"
                        onClick={() => setTreatmentWorkspaceOpen(true)}
                      >
                        Review or Change Treatments
                      </button>
                    </div>
                    <div className="mt-3 flex flex-wrap gap-2 text-[10px] font-semibold">
                      <span className="rounded-full border border-emerald-200 bg-white px-2.5 py-1 text-emerald-900">
                        Reviewed: {reviewedCount}/{likelyVariables.length}
                      </span>
                      <span className="rounded-full border border-emerald-200 bg-white px-2.5 py-1 text-emerald-900">
                        Durable revision: {durableReview?.revision ?? "Unavailable"}
                      </span>
                      <span className="rounded-full border border-emerald-200 bg-white px-2.5 py-1 text-emerald-900">
                        Evidence: {state.evidenceStatus.replace(/_/g, " ")}
                      </span>
                      {treatmentCounts.map(([handling, count]) => (
                        <span
                          key={handling}
                          className="rounded-full border border-emerald-200 bg-white px-2.5 py-1 text-emerald-900"
                        >
                          {handlingLabels[handling]}: {count}
                        </span>
                      ))}
                      <span className="rounded-full border border-emerald-200 bg-white px-2.5 py-1 text-emerald-900">
                        Value-level overrides: {totalOverrideCount}
                      </span>
                    </div>
                  </div>
                ) : (
                <div
                  className="overflow-hidden rounded-xl border border-indigo-300 bg-indigo-50/60"
                  data-testid="special-value-treatment-review"
                >
                  <div className="flex flex-col gap-2 border-b border-indigo-300 bg-indigo-900 px-4 py-3 text-white lg:flex-row lg:items-start lg:justify-between">
                    <div>
                      <div className="text-[10px] font-semibold uppercase tracking-wide text-violet-200">
                        Governed data-quality contract
                      </div>
                      <h3 className="mt-1 text-base font-semibold text-white">
                        Feature-level Special-Value Treatment Table
                      </h3>
                      <p className="mt-1 max-w-4xl text-xs leading-5 text-indigo-100">
                        Review every affected feature in one table. Expand a
                        row to inspect each observed code, target-rate
                        evidence, overrides, and required rationale.
                      </p>
                      <p
                        className="mt-2 max-w-4xl rounded-lg border border-violet-300/50 bg-white/10 px-3 py-2 text-xs font-medium leading-5 text-indigo-50"
                        data-testid="special-value-treatment-help"
                      >
                        Choose the modeling outcome in plain language: create
                        an indicator (dummy) variable, impute with a valid
                        value, exclude the predictor from modeling, or leave
                        the special value unchanged.
                      </p>
                    </div>
                    <div className="flex flex-wrap items-center gap-2">
                      <span
                        className={`rounded-full border px-3 py-1 text-xs font-semibold ${
                        (draftDirty ? draftUnresolvedCount : unresolvedCount)
                          ? "border-amber-300 bg-amber-100 text-amber-950"
                          : "border-emerald-300 bg-emerald-100 text-emerald-900"
                      }`}
                      >
                      {(draftDirty ? draftUnresolvedCount : unresolvedCount)
                        ? `${draftDirty ? draftUnresolvedCount : unresolvedCount} unresolved`
                        : "All policies reviewable"}
                      </span>
                      {confirmedAndClean ? (
                        <button
                          type="button"
                          className="rounded-lg border border-indigo-300 bg-white/10 px-3 py-1 text-xs font-semibold text-white hover:bg-white/20"
                          onClick={() => {
                            setSelectedVariable("");
                            setTreatmentWorkspaceOpen(false);
                          }}
                        >
                          Close review
                        </button>
                      ) : null}
                    </div>
                  </div>

                  <div className="space-y-4 p-4">
                    <div
                      className="grid gap-2 rounded-xl border border-indigo-200 bg-white p-3 sm:grid-cols-2"
                      data-testid="special-value-analytical-scope"
                      data-structural-scope={result.scope}
                      data-target-analysis-scope={result.target_analysis_scope}
                      data-final-holdout-accessed={String(result.final_holdout_accessed)}
                    >
                      <div className="rounded-lg border border-blue-200 bg-blue-50 px-3 py-2">
                        <div className="text-[10px] font-bold uppercase tracking-wide text-blue-700">
                          Structural counts
                        </div>
                        <p className="mt-1 text-xs leading-5 text-blue-950">
                          Full governed population: {result.row_count.toLocaleString()} rows.
                          Counts, prevalence, nulls, parse failures, and ordinary
                          values use this scope.
                        </p>
                      </div>
                      <div className="rounded-lg border border-violet-200 bg-violet-50 px-3 py-2">
                        <div className="text-[10px] font-bold uppercase tracking-wide text-violet-700">
                          Target-rate evidence
                        </div>
                        <p className="mt-1 text-xs leading-5 text-violet-950">
                          Development population only
                          {result.development_partition_id
                            ? ` (${result.development_partition_id})`
                            : ""}. The sealed final holdout was not accessed.
                        </p>
                      </div>
                    </div>

                    <div
                      className="rounded-xl border border-slate-200 bg-white p-3"
                      data-testid="special-value-feature-toolbar"
                    >
                      <div className="flex items-center gap-2 text-sm font-semibold text-slate-950">
                        <Filter size={15} className="text-blue-700" aria-hidden="true" />
                        Find and organize affected features
                        {firstUnresolvedVariable ? (
                          <button
                            type="button"
                            className="atlas-secondary-button ml-auto text-xs"
                            onClick={revealFirstUnresolved}
                            data-testid="go-to-first-unresolved-special-value"
                          >
                            Go to first unresolved
                          </button>
                        ) : null}
                      </div>
                      <div className="mt-3 grid gap-2 md:grid-cols-2 xl:grid-cols-4">
                        <label className="relative block">
                          <span className="atlas-label">Search features</span>
                          <Search
                            size={14}
                            className="pointer-events-none absolute left-3 top-8 text-slate-400"
                            aria-hidden="true"
                          />
                          <input
                            className="atlas-input mt-1 pl-9"
                            value={variableSearch}
                            onChange={(event) => setVariableSearch(event.target.value)}
                            placeholder="Feature, signal, or definition"
                            data-testid="special-value-feature-search"
                          />
                        </label>
                        <label>
                          <span className="atlas-label">Review status</span>
                          <select
                            className="atlas-input mt-1"
                            value={reviewFilter}
                            data-testid="special-value-status-filter"
                            onChange={(event) =>
                              setReviewFilter(
                                event.target.value as
                                  | "all"
                                  | "reviewed"
                                  | "unreviewed"
                                  | "unresolved",
                              )
                            }
                          >
                            <option value="all">All statuses</option>
                            <option value="unresolved">Rationale required</option>
                            <option value="unreviewed">Open or draft</option>
                            <option value="reviewed">Durably reviewed</option>
                          </select>
                        </label>
                        <label>
                          <span className="atlas-label">Selected treatment</span>
                          <select
                            className="atlas-input mt-1"
                            value={treatmentFilter}
                            data-testid="special-value-treatment-filter"
                            onChange={(event) =>
                              setTreatmentFilter(
                                event.target.value as "all" | BureauHandling,
                              )
                            }
                          >
                            <option value="all">All treatments</option>
                            {Object.entries(handlingLabels).map(([value, label]) => (
                              <option key={value} value={value}>
                                {label}
                              </option>
                            ))}
                          </select>
                        </label>
                        <label>
                          <span className="atlas-label">Sort</span>
                          <select
                            className="atlas-input mt-1"
                            value={variableSort}
                            data-testid="special-value-feature-sort"
                            onChange={(event) =>
                              setVariableSort(
                                event.target.value as SpecialValueVariableSort,
                              )
                            }
                          >
                            <option value="unresolved_first">Unresolved first</option>
                            <option value="prevalence_desc">Prevalence: high to low</option>
                            <option value="prevalence_asc">Prevalence: low to high</option>
                            <option value="affected_rows_desc">Affected rows: high to low</option>
                            <option value="special_code_count_desc">Special-code count: high to low</option>
                            <option value="event_rate_delta_desc">Absolute event-rate difference: high to low</option>
                            <option value="name">Feature name</option>
                          </select>
                        </label>
                      </div>
                      <div className="mt-3 flex flex-col gap-2 rounded-lg border border-blue-200 bg-blue-50 p-3 lg:flex-row lg:items-end lg:justify-between">
                        <label className="w-full max-w-xl">
                          <span className="atlas-label">Bulk treatment for filtered features</span>
                          <select
                            className="atlas-input mt-1"
                            value={bulkHandling}
                            data-testid="special-value-bulk-treatment"
                            onChange={(event) =>
                              setBulkHandling(event.target.value as "" | BureauHandling)
                            }
                          >
                            <option value="">Select a treatment</option>
                            {selectableHandlingEntries().map((option) => (
                              <option key={option.value} value={option.value}>
                                {option.label}
                              </option>
                            ))}
                          </select>
                        </label>
                        {bulkHandling === "documented_domain_mapping" ? (
                          <label className="w-full max-w-sm">
                            <span className="atlas-label">
                              Governed replacement value · required
                            </span>
                            <input
                              className="atlas-input mt-1"
                              value={bulkReplacementValue}
                              onChange={(event) =>
                                setBulkReplacementValue(event.target.value)
                              }
                              data-testid="special-value-bulk-replacement"
                              placeholder="Value applied to each eligible feature"
                            />
                          </label>
                        ) : null}
                        <button
                          type="button"
                          className="atlas-secondary-button"
                          data-testid="apply-bulk-special-value-treatment"
                          disabled={
                            !bulkHandling ||
                            !unresolvedFilteredCount ||
                            (bulkHandling === "documented_domain_mapping" &&
                              !bulkReplacementValue.trim())
                          }
                          onClick={applyBulkTreatment}
                        >
                          Apply selected default to unresolved attributes
                        </button>
                      </div>
                      <p className="mt-2 text-xs leading-5 text-slate-600">
                        {unresolvedFilteredCount.toLocaleString()} durably open filtered attribute{unresolvedFilteredCount === 1 ? "" : "s"} have no explicit unsaved edit and are eligible. Selecting a bulk treatment changes nothing until you
                        press Apply. Rows with an explicit browser edit are never overwritten. Applied changes remain a browser draft; they are neither saved nor confirmed automatically.
                      </p>
                    </div>

                    <div className="max-w-full overflow-auto rounded-xl border border-slate-200 bg-white shadow-sm">
                      <table
                        className="w-full min-w-[2460px] border-separate border-spacing-0 text-xs"
                        data-testid="special-value-feature-table"
                      >
                        <thead className="sticky top-0 z-20 bg-slate-950 text-white shadow-sm">
                          <tr>
                            <TableHeader className="w-64">Attribute</TableHeader>
                            <TableHeader className="w-40">Catalog match state</TableHeader>
                            <SortableTableHeader
                              className="w-28 text-right"
                              label="Number of special codes"
                              current={variableSort}
                              descending="special_code_count_desc"
                              ascending="special_code_count_asc"
                              onChange={setVariableSort}
                            />
                            <TableHeader className="w-80">Special-code summary</TableHeader>
                            <SortableTableHeader
                              className="w-28 text-right"
                              label="Affected rows"
                              current={variableSort}
                              descending="affected_rows_desc"
                              ascending="affected_rows_asc"
                              onChange={setVariableSort}
                            />
                            <SortableTableHeader
                              className="w-28 text-right"
                              label="Population percentage"
                              current={variableSort}
                              descending="prevalence_desc"
                              ascending="prevalence_asc"
                              onChange={setVariableSort}
                            />
                            <SortableTableHeader
                              className="w-36 text-right"
                              label="Largest event-rate difference"
                              current={variableSort}
                              descending="event_rate_delta_desc"
                              ascending="event_rate_delta_asc"
                              onChange={setVariableSort}
                            />
                            <TableHeader className="w-64">Recommended treatment</TableHeader>
                            <TableHeader className="w-72">Selected treatment</TableHeader>
                            <TableHeader className="w-40">Rationale status</TableHeader>
                            <TableHeader className="w-24 text-right">Overrides</TableHeader>
                            <TableHeader className="w-40">Review status</TableHeader>
                            <TableHeader className="w-36">Details action</TableHeader>
                          </tr>
                        </thead>
                        <tbody>
                          {filteredVariables.map((variable, variableIndex) => {
                            const review = reviewByVariable.get(variable.variable);
                            const policy = explicitVariableDefault(
                              state,
                              variable.variable,
                            );
                            const overrides = state.decisions.filter(
                              (decision) => decision.variable === variable.variable,
                            ).length;
                            const largestDelta = largestEventRateDifference(variable);
                            const semanticAnnotation = semanticAnnotationByField.get(
                              variable.variable,
                            );
                            const catalogMatch = catalogMatchPresentation(
                              semanticAnnotations,
                              semanticAnnotation,
                            );
                            const expanded = activeVariable?.variable === variable.variable;
                            const detailsId = `special-value-details-${variableIndex}-${variable.variable.replace(/[^A-Za-z0-9_-]/g, "-")}`;
                            const rowState = review?.unresolved
                              ? "Rationale required"
                              : draftDirty && !review?.reviewed
                                ? "Draft ready to save"
                                : review?.reviewed
                                  ? "Durably reviewed"
                                  : "Open for review";
                            return (
                              <Fragment key={variable.variable}>
                                <tr
                                  id={`special-value-feature-row-${variableDomToken(variable.variable)}`}
                                  className={
                                    review?.unresolved
                                      ? "bg-amber-50/70"
                                      : "odd:bg-white even:bg-slate-50/70"
                                  }
                                  data-testid="special-value-feature-row"
                                  data-special-value-variable={variable.variable}
                                  data-review-state={rowState}
                                >
                                  <BodyCell className="whitespace-normal">
                                    <div className="font-semibold text-slate-950">
                                      {variable.variable}
                                    </div>
                                    <div className="mt-1 text-[10px] text-slate-500">
                                      {variable.datatype} · {variable.special_values.length} observed definition{variable.special_values.length === 1 ? "" : "s"}
                                    </div>
                                  </BodyCell>
                                  <BodyCell>
                                    <span
                                      className={`inline-flex rounded-full border px-2 py-1 text-[10px] font-semibold ${catalogMatch.className}`}
                                      data-testid={`bureau-catalog-match-${variable.variable}`}
                                      data-authority-state={
                                        semanticAnnotation?.authorityState ??
                                        "non_authoritative_unresolved"
                                      }
                                    >
                                      {catalogMatch.label}
                                    </span>
                                  </BodyCell>
                                  <NumericCell>{variable.special_values.length.toLocaleString()}</NumericCell>
                                  <BodyCell className="whitespace-normal">
                                    <div className="space-y-1">
                                      {variable.special_values.slice(0, 2).map((profile) => (
                                        <div key={profile.value} className="leading-4 text-slate-700">
                                          <span className="font-mono font-semibold text-violet-900">{profile.value}</span>
                                          {" — "}{profile.definition}
                                        </div>
                                      ))}
                                      {variable.special_values.length > 2 ? (
                                        <div className="text-[10px] text-slate-500">
                                          +{variable.special_values.length - 2} more code definition{variable.special_values.length - 2 === 1 ? "" : "s"}
                                        </div>
                                      ) : null}
                                    </div>
                                  </BodyCell>
                                  <NumericCell>{variable.special_value_count.toLocaleString()}</NumericCell>
                                  <NumericCell>{pct(variable.special_value_frequency)}</NumericCell>
                                  <NumericCell>
                                    {largestDelta == null
                                      ? "Not available"
                                      : `${largestDelta >= 0 ? "+" : ""}${pct(largestDelta)}`}
                                  </NumericCell>
                                  <BodyCell className="whitespace-normal leading-5 text-slate-700">
                                    {recommendedFeatureTreatment(variable)}
                                  </BodyCell>
                                  <BodyCell>
                                    <select
                                      id={`special-value-treatment-${variableDomToken(variable.variable)}`}
                                      className="atlas-input min-w-64"
                                      aria-label={`Selected treatment for ${variable.variable}`}
                                      data-testid={`special-value-treatment-${variable.variable}`}
                                      value={policy?.handling ?? ""}
                                      onChange={(event) => {
                                        const handling = event.target.value as BureauHandling;
                                        updateVariableDefault(variable.variable, { handling });
                                        if (treatmentRequiresRationale(handling, false)) {
                                          setSelectedVariable(variable.variable);
                                        }
                                      }}
                                    >
                                      <option value="" disabled>Select treatment</option>
                                      {selectableHandlingEntries(policy?.handling).map((option) => (
                                        <option key={option.value} value={option.value}>
                                          {option.label}
                                        </option>
                                      ))}
                                    </select>
                                  </BodyCell>
                                  <BodyCell>
                                    <span className={review?.unresolved ? "font-semibold text-amber-800" : "text-slate-600"}>
                                      {review?.unresolved
                                        ? "Required — open details"
                                        : policy && treatmentRequiresRationale(policy.handling, false)
                                          ? "Rationale complete"
                                          : "Not required"}
                                    </span>
                                  </BodyCell>
                                  <NumericCell>{overrides.toLocaleString()}</NumericCell>
                                  <BodyCell>
                                    <span
                                      className={`inline-flex items-center gap-1 rounded-full border px-2 py-1 text-[10px] font-semibold ${
                                        review?.unresolved
                                          ? "border-amber-200 bg-amber-50 text-amber-900"
                                          : review?.reviewed
                                            ? "border-emerald-200 bg-emerald-50 text-emerald-800"
                                            : "border-blue-200 bg-blue-50 text-blue-800"
                                      }`}
                                    >
                                      {review?.unresolved ? (
                                        <CircleAlert size={12} aria-hidden="true" />
                                      ) : (
                                        <CheckCircle2 size={12} aria-hidden="true" />
                                      )}
                                      {rowState}
                                    </span>
                                  </BodyCell>
                                  <BodyCell>
                                    <button
                                      type="button"
                                      className="atlas-secondary-button text-xs"
                                      aria-expanded={expanded}
                                      aria-controls={detailsId}
                                      data-testid={`review-special-value-codes-${variable.variable}`}
                                      onClick={() =>
                                        setSelectedVariable(expanded ? "" : variable.variable)
                                      }
                                    >
                                      <ChevronDown
                                        size={14}
                                        className={expanded ? "rotate-180" : ""}
                                        aria-hidden="true"
                                      />
                                      {expanded ? "Hide codes" : "Review codes"}
                                    </button>
                                  </BodyCell>
                                </tr>
                                {expanded ? (
                                  <tr id={detailsId} data-testid="special-value-code-details-row">
                                    <td colSpan={13} className="border-b border-indigo-200 bg-indigo-50 p-4">
                                      <VariableTreatmentWorkspace
                                        variable={variable}
                                        semanticAnnotation={semanticAnnotation}
                                        semanticAnnotationContract={semanticAnnotations}
                                        state={state}
                                        durableReviewed={Boolean(review?.reviewed)}
                                        onDefault={updateVariableDefault}
                                        onOverride={updateOverride}
                                        onOverrideRationale={updateOverrideRationale}
                                        onOverrideReplacement={updateOverrideReplacement}
                                      />
                                    </td>
                                  </tr>
                                ) : null}
                              </Fragment>
                            );
                          })}
                          {!filteredVariables.length ? (
                            <tr>
                              <td colSpan={13} className="p-8 text-center text-sm text-slate-500">
                                No affected features match the current search and filters.
                              </td>
                            </tr>
                          ) : null}
                        </tbody>
                      </table>
                    </div>
                    <p className="text-xs leading-5 text-slate-600">
                      Showing {filteredVariables.length.toLocaleString()} of {likelyVariables.length.toLocaleString()} affected features. Open requirements are listed first by default.
                    </p>
                  </div>
                </div>
                )
              ) : null}

              {!result.detected && state.declaration === "auto" ? (
                <div className="rounded-lg border border-slate-200 bg-white p-3 text-sm text-slate-600">
                  No variable met the multi-signal bureau threshold. A generic
                  field containing a special-looking value is not classified
                  as bureau data without supporting name, metadata,
                  concentration, or reviewer evidence.
                </div>
              ) : null}
            </>
          ) : null}

          <div className="flex flex-col gap-3 rounded-xl border border-slate-200 bg-white p-4 sm:flex-row sm:items-center sm:justify-between">
            <div>
              <div className="text-sm font-semibold text-slate-950">
                Section completion
              </div>
              <div className="mt-1 text-xs leading-5 text-slate-600">
                {loading
                  ? "Loading the exact durable review authority. Continuation remains blocked."
                  : error
                    ? "The durable review authority is unavailable. Continuation remains blocked."
                    : draftDirty
                      ? "This browser draft has unsaved changes and is not authoritative. Save or confirm it before continuing."
                      : unresolvedCount
                        ? `${unresolvedCount} backend-detected variable${unresolvedCount === 1 ? " remains" : "s remain"} open in durable revision ${durableReview?.revision ?? "unavailable"}.`
                        : durableReview?.status === "confirmed"
                          ? `The backend treatment contract is confirmed at durable revision ${durableReview.revision}.`
                          : durableReview?.status === "not_required"
                            ? `The backend reports that review is not required at durable revision ${durableReview.revision}.`
                            : "All backend-detected variables are durably reviewed. Confirm the contract to continue."}
              </div>
              {message ? (
                <div className="mt-1 text-xs font-medium text-blue-800">
                  {message}
                </div>
              ) : null}
            </div>
            {confirmedAndClean && !treatmentWorkspaceOpen ? (
              <span
                className="inline-flex items-center gap-2 rounded-full border border-emerald-200 bg-emerald-50 px-3 py-2 text-xs font-semibold text-emerald-900"
                data-testid="special-value-confirmed-revision"
              >
                <CheckCircle2 size={14} aria-hidden="true" />
                Confirmed revision {durableReview?.revision}
              </span>
            ) : (
              <div className="flex flex-wrap gap-2">
                <button
                  type="button"
                  className="atlas-secondary-button"
                  onClick={() => void persistReview("draft")}
                  disabled={!result || !durableReview || saving}
                >
                  <Save size={15} /> Save Draft Review
                </button>
                <button
                  type="button"
                  className="atlas-primary-button"
                  onClick={() => void persistReview("confirmed")}
                  disabled={
                    !result ||
                    !durableReview ||
                    saving ||
                    draftUnresolvedCount > 0
                  }
                  title={
                    draftUnresolvedCount
                      ? "Resolve every missing treatment, governed replacement, and rationale before confirmation."
                      : "Submit this exact-version draft to the backend for governed confirmation."
                  }
                >
                  {saving ? (
                    <CircleAlert size={15} />
                  ) : (
                    <CheckCircle2 size={15} />
                  )}
                  Confirm Special-Value Treatment
                </button>
              </div>
            )}
          </div>
        </div>
      </div>
    </section>
  );
}

function BureauSemanticDetails({
  variable,
  annotation,
  contract,
}: {
  variable: BureauDetectionVariable;
  annotation?: BureauSemanticAnnotation;
  contract: BureauSemanticAnnotationContract | null;
}) {
  const verifiedCatalogDefinition = Boolean(
    contract?.state === "available" &&
      annotation?.providerAuthoritative &&
      annotation.mappingAccepted &&
      (annotation.mappingState === "exact_verified" ||
        annotation.mappingState === "approved_alias"),
  );
  const providerRange = annotation?.ordinaryRange
    ? annotation.ordinaryRange.expression ??
      [annotation.ordinaryRange.minimum, annotation.ordinaryRange.maximum]
        .filter(Boolean)
        .join(" to ")
    : "Not supplied in this bounded annotation";
  const compactReference = (value?: string) =>
    value ? `${value.slice(0, 12)}…` : "Not supplied";
  return (
    <div
      className="grid gap-3 lg:grid-cols-2 xl:grid-cols-5"
      data-testid="bureau-semantic-source-details"
    >
      <section className="rounded-xl border border-emerald-200 bg-emerald-50 p-3">
        <h5 className="text-xs font-semibold text-emerald-950">
          Provider catalog definition
        </h5>
        {verifiedCatalogDefinition && annotation ? (
          <div className="mt-2 space-y-1 text-xs leading-5 text-emerald-950">
            <div>
              <span className="font-semibold">Attribute:</span>{" "}
              {annotation.candidateAttributeCode}
            </div>
            <div>
              <span className="font-semibold">Catalog:</span>{" "}
              {annotation.catalogKey.provider} · {annotation.catalogKey.product} ·{" "}
              {annotation.catalogKey.edition} · {annotation.catalogKey.dictionaryVersion}
            </div>
            <div>
              <span className="font-semibold">Description:</span>{" "}
              {annotation.description ?? "Not supplied in this bounded annotation"}
            </div>
            <div>
              <span className="font-semibold">Data type / units:</span>{" "}
              {[annotation.dataType, annotation.units].filter(Boolean).join(" · ") || "Not supplied"}
            </div>
            <div>
              <span className="font-semibold">Ordinary range:</span>{" "}
              {providerRange}
            </div>
            {annotation.specialDefinitions.length ? (
              <ul className="mt-1 space-y-1">
                {annotation.specialDefinitions.slice(0, 6).map((definition) => (
                  <li key={definition.definitionId}>
                    <span className="font-mono font-semibold">
                      {definition.valueCode}
                    </span>{" "}
                    — {definition.meaning}{" "}
                    <span className="text-emerald-800">
                      ({definition.semanticFamily.replace(/_/g, " ")})
                    </span>
                  </li>
                ))}
              </ul>
            ) : (
              <div>No bounded provider special-code definition was supplied.</div>
            )}
            <div className="border-t border-emerald-200 pt-1 text-[11px] text-emerald-800">
              Catalog version {annotation.catalogVersionId} · catalog checksum{" "}
              <span title={annotation.catalogChecksum}>
                {compactReference(annotation.catalogChecksum)}
              </span>
              {annotation.attributeDefinitionChecksum ? (
                <>
                  {" "}· definition checksum{" "}
                  <span title={annotation.attributeDefinitionChecksum}>
                    {compactReference(annotation.attributeDefinitionChecksum)}
                  </span>
                </>
              ) : null}
            </div>
          </div>
        ) : (
          <p className="mt-2 text-xs leading-5 text-slate-700">
            No entitled, exact-version provider definition is authoritative for this field.
          </p>
        )}
      </section>

      <section className="rounded-xl border border-blue-200 bg-blue-50 p-3">
        <h5 className="text-xs font-semibold text-blue-950">
          Analyst-approved crosswalk
        </h5>
        {annotation?.mappingAccepted ? (
          <div className="mt-2 space-y-1 text-xs leading-5 text-blue-950">
            <div>Mapping state: {annotation.mappingState.replace(/_/g, " ")}</div>
            <div>Authority basis: {annotation.authorityState.replace(/_/g, " ")}</div>
            <div>
              Crosswalk: {annotation.crosswalkId ?? "Direct exact mapping"}
              {annotation.crosswalkRevision
                ? ` · revision ${annotation.crosswalkRevision}`
                : ""}
            </div>
            <div>Binding: {annotation.bindingId} · revision {annotation.bindingRevision}</div>
            <div>Catalog revision: {annotation.catalogVersionId}</div>
            <div className="text-[11px] text-blue-800">
              Annotation reference: {annotation.annotationId}
            </div>
          </div>
        ) : (
          <p className="mt-2 text-xs leading-5 text-slate-700">
            No analyst-approved crosswalk annotation is available for this field.
          </p>
        )}
      </section>

      <section className="rounded-xl border border-slate-200 bg-white p-3">
        <h5 className="text-xs font-semibold text-slate-950">
          Dataset-observed behavior
        </h5>
        <div className="mt-2 space-y-1 text-xs leading-5 text-slate-700">
          <div>{variable.special_value_count.toLocaleString()} observed special values</div>
          <div>{pct(variable.special_value_frequency)} of the governed population</div>
          <div>
            {variable.special_values
              .slice(0, 4)
              .map((profile) => `${profile.value}: ${profile.count.toLocaleString()}`)
              .join(" · ") || "No observed special-code profile"}
          </div>
        </div>
      </section>

      <section className="rounded-xl border border-violet-200 bg-violet-50 p-3">
        <h5 className="text-xs font-semibold text-violet-950">ATLAS heuristic detection</h5>
        <div className="mt-2 space-y-1 text-xs leading-5 text-violet-950">
          <div>{Math.round(variable.confidence * 100)}% bureau-detection confidence</div>
          <div>{variable.reasons.join(" · ") || "No heuristic reason supplied"}</div>
          <div>Heuristic evidence never supplies a provider definition.</div>
        </div>
      </section>

      <section className="rounded-xl border border-amber-200 bg-amber-50 p-3">
        <h5 className="text-xs font-semibold text-amber-950">
          Unverified candidate
        </h5>
        <p className="mt-2 text-xs leading-5 text-amber-950">
          {verifiedCatalogDefinition
            ? "No unverified candidate is being presented; the mapping above is analyst accepted and exact-version bound."
            : annotation?.candidateAttributeCode
              ? `${annotation.candidateAttributeCode} remains non-authoritative (${annotation.mappingState.replace(/_/g, " ")}). ${annotation.nonAuthoritativeReasons.map((reason) => reason.replace(/_/g, " ")).join(" · ")}`
              : "No authoritative catalog mapping is available for this field. ATLAS will continue to show observed special-value behavior, but it will not assign a provider definition without approved mapping evidence."}
        </p>
      </section>
    </div>
  );
}

function VariableTreatmentWorkspace({
  variable,
  semanticAnnotation,
  semanticAnnotationContract,
  state,
  durableReviewed,
  onDefault,
  onOverride,
  onOverrideRationale,
  onOverrideReplacement,
}: {
  variable: BureauDetectionVariable;
  semanticAnnotation?: BureauSemanticAnnotation;
  semanticAnnotationContract: BureauSemanticAnnotationContract | null;
  state: BureauReviewState;
  durableReviewed: boolean;
  onDefault: (
    variable: string,
    patch: Partial<BureauVariableDefault>,
  ) => void;
  onOverride: (
    variable: string,
    value: number,
    handling: "" | BureauHandling,
  ) => void;
  onOverrideRationale: (
    variable: string,
    value: number,
    rationale: string,
  ) => void;
  onOverrideReplacement: (
    variable: string,
    value: number,
    replacementValue: string,
  ) => void;
}) {
  const policy = explicitVariableDefault(state, variable.variable);
  const policyNeedsRationale = Boolean(
    policy && treatmentRequiresRationale(policy.handling, false),
  );
  const reviewed = reviewStateForVariable(state, variable);
  return (
    <div className="min-w-0 space-y-3">
      <div
        className="rounded-xl border border-slate-200 bg-white p-4"
        data-testid="special-value-variable-summary"
      >
        <div className="flex flex-col gap-3 lg:flex-row lg:items-start lg:justify-between">
          <div className="min-w-0">
            <div className="text-[10px] font-semibold uppercase tracking-wide text-slate-500">
              Variable summary
            </div>
            <h4 className="mt-1 break-words text-base font-semibold text-slate-950">
              {variable.variable}
            </h4>
            <div className="mt-2 flex flex-wrap gap-2">
              <Badge>
                {Math.round(variable.confidence * 100)}% detection confidence
              </Badge>
              <Badge>
                {variable.special_value_count.toLocaleString()} special values
              </Badge>
              <Badge>{pct(variable.special_value_frequency)} prevalence</Badge>
              <Badge>
                {variable.ordinary_value_count.toLocaleString()} ordinary
                values
              </Badge>
              <Badge>
                {variable.special_values.length.toLocaleString()} observed
                definitions
              </Badge>
              <span
                className={`rounded-full border px-2.5 py-1 text-[10px] font-semibold ${
                  durableReviewed
                    ? "border-emerald-200 bg-emerald-50 text-emerald-800"
                    : "border-amber-200 bg-amber-50 text-amber-900"
                }`}
              >
                {durableReviewed
                  ? "Durably reviewed"
                  : reviewed.reviewed
                    ? "Draft ready to save"
                    : "Review required"}
              </span>
            </div>
          </div>
          <div className="grid min-w-[280px] gap-2">
            <label>
              <span className="atlas-label">
                Default action for special values
              </span>
              <select
                id={`special-value-detail-treatment-${variableDomToken(variable.variable)}`}
                className="atlas-input mt-1"
                value={policy?.handling ?? ""}
                onChange={(event) =>
                  onDefault(variable.variable, {
                    handling: event.target.value as BureauHandling,
                  })
                }
              >
                <option value="" disabled>Select treatment</option>
                {selectableHandlingEntries(policy?.handling).map((option) => (
                  <option key={option.value} value={option.value}>
                    {option.label}
                  </option>
                ))}
              </select>
              <span
                className="mt-1 block text-xs leading-5 text-slate-600"
                data-testid="selected-special-value-treatment-help"
              >
                {policy
                  ? handlingHelp[policy.handling]
                  : "Select an explicit feature-level treatment before saving or confirming this review."}
              </span>
            </label>
            {policy && treatmentRequiresReplacement(policy.handling) ? (
              <label>
                <span className="atlas-label">
                  Governed replacement value · required
                </span>
                <input
                  id={`special-value-replacement-${variableDomToken(variable.variable)}`}
                  className={`atlas-input mt-1 ${
                    policy.replacementValue?.trim()
                      ? ""
                      : "border-amber-400 bg-amber-50"
                  }`}
                  value={policy.replacementValue ?? ""}
                  onChange={(event) =>
                    onDefault(variable.variable, {
                      replacementValue: event.target.value,
                    })
                  }
                  placeholder="Enter the valid governed replacement"
                  data-testid={`special-value-replacement-${variable.variable}`}
                />
              </label>
            ) : null}
            {policy && policyNeedsRationale ? (
              <label>
                <span className="atlas-label">
                  Variable-level rationale · required
                </span>
                <textarea
                  id={`special-value-rationale-${variableDomToken(variable.variable)}`}
                  className="atlas-input mt-1 min-h-20 resize-y"
                  value={policy.rationale}
                  onChange={(event) =>
                    onDefault(variable.variable, {
                      rationale: event.target.value,
                    })
                  }
                  placeholder="Explain the destructive, replacement, exclusion, or custom policy."
                />
              </label>
            ) : policy ? (
              <div className="rounded-lg border border-emerald-100 bg-emerald-50 px-3 py-2 text-xs leading-5 text-emerald-900">
                This governed default applies to every compatible row. A
                separate rationale is needed only for an override or
                destructive treatment.
              </div>
            ) : (
              <div className="rounded-lg border border-amber-200 bg-amber-50 px-3 py-2 text-xs leading-5 text-amber-950">
                No treatment has been selected. Choose an explicit feature-level policy or use the bulk draft action before saving or confirming.
              </div>
            )}
          </div>
        </div>
        <div className="mt-3 grid gap-2 sm:grid-cols-3">
          <SmallMetric label="Null missing values" value={variable.null_count} />
          <SmallMetric
            label="Parse failures"
            value={variable.parse_failure_count}
          />
          <SmallMetric
            label="Ordinary-value count"
            value={variable.ordinary_value_count}
          />
        </div>
      </div>

      <BureauSemanticDetails
        variable={variable}
        annotation={semanticAnnotation}
        contract={semanticAnnotationContract}
      />

      <div
        className="max-w-full overflow-auto rounded-xl border border-slate-200 bg-white shadow-sm"
        data-testid="special-value-treatment-table"
        data-target-analysis-scope="development_population"
        data-final-holdout-accessed="false"
      >
        <table className="w-full min-w-[1900px] border-separate border-spacing-0 text-xs">
          <thead className="sticky top-0 z-20 bg-slate-950 text-white shadow-sm">
            <tr>
              <TableHeader className="w-28 text-right">
                Special value
              </TableHeader>
              <TableHeader className="w-64">Definition</TableHeader>
              <TableHeader className="w-24 text-right">Count</TableHeader>
              <TableHeader className="w-32 text-right">
                Population share
              </TableHeader>
              <TableHeader className="w-28 text-right">
                Development event count
              </TableHeader>
              <TableHeader className="w-28 text-right">
                Development event rate
              </TableHeader>
              <TableHeader className="w-36 text-right">
                Development regular-value event rate
              </TableHeader>
              <TableHeader className="w-36 text-right">
                Development event-rate difference
              </TableHeader>
              <TableHeader className="w-56">Default action</TableHeader>
              <TableHeader className="w-64">
                Override action
              </TableHeader>
              <TableHeader className="w-80">Rationale</TableHeader>
              <TableHeader className="w-32">Review status</TableHeader>
            </tr>
          </thead>
          <tbody>
            {variable.special_values.map((profile) => {
              const override = valueOverride(
                state,
                variable.variable,
                profile.value,
              );
              const effectiveHandling =
                override?.handling ?? policy?.handling ?? null;
              const rationaleRequired = effectiveHandling
                ? treatmentRequiresRationale(effectiveHandling, !!override)
                : true;
              const rationale = override?.rationale ?? policy?.rationale ?? "";
              const replacementValue =
                override?.replacementValue ?? policy?.replacementValue ?? "";
              const rowReady =
                Boolean(effectiveHandling) &&
                (!rationaleRequired || !!rationale.trim()) &&
                (!effectiveHandling ||
                  !treatmentRequiresReplacement(effectiveHandling) ||
                  !!replacementValue.trim());
              return (
                <tr
                  key={`${variable.variable}-${profile.value}`}
                  className="odd:bg-white even:bg-slate-50/70"
                >
                  <NumericCell className="bg-violet-50 text-sm font-bold text-violet-900">
                    {profile.value}
                  </NumericCell>
                  <BodyCell className="whitespace-normal break-words leading-5 text-slate-700">
                    {profile.definition}
                  </BodyCell>
                  <NumericCell>{profile.count.toLocaleString()}</NumericCell>
                  <NumericCell>{pct(profile.frequency)}</NumericCell>
                  <NumericCell>
                    {profile.event_count?.toLocaleString() ??
                      "Not available"}
                  </NumericCell>
                  <NumericCell>{pct(profile.event_rate)}</NumericCell>
                  <NumericCell>
                    {pct(profile.regular_event_rate)}
                  </NumericCell>
                  <NumericCell
                    className={
                      typeof profile.event_rate_delta === "number" &&
                      Math.abs(profile.event_rate_delta) >= 0.05
                        ? "font-semibold text-amber-800"
                        : ""
                    }
                  >
                    {typeof profile.event_rate_delta === "number"
                      ? `${profile.event_rate_delta >= 0 ? "+" : ""}${pct(profile.event_rate_delta)}`
                      : "Not available"}
                  </NumericCell>
                  <BodyCell>
                    <span className="inline-flex max-w-full whitespace-normal rounded-full border border-violet-200 bg-violet-50 px-2.5 py-1 text-[10px] font-semibold leading-4 text-violet-900">
                      {policy
                        ? handlingLabels[policy.handling]
                        : "No feature-level treatment selected"}
                    </span>
                  </BodyCell>
                  <BodyCell>
                    <div className="flex items-center gap-2">
                      <select
                        className="atlas-input min-w-52"
                        aria-label={`Override handling for ${variable.variable} ${profile.value}`}
                        disabled={!policy}
                        value={override?.handling ?? ""}
                        onChange={(event) =>
                          onOverride(
                            variable.variable,
                            profile.value,
                            event.target.value as "" | BureauHandling,
                          )
                        }
                      >
                        <option value="">Use variable default</option>
                        {selectableHandlingEntries(
                          override?.handling ?? policy?.handling,
                        ).map((option) => (
                          <option key={option.value} value={option.value}>
                            {option.label}
                          </option>
                        ))}
                      </select>
                      {override ? (
                        <span className="rounded-full border border-violet-200 bg-violet-50 px-2 py-1 text-[9px] font-bold uppercase text-violet-800">
                          Override
                        </span>
                      ) : null}
                    </div>
                  </BodyCell>
                  <BodyCell>
                    {override ? (
                      <div className="min-w-72 space-y-2">
                        {treatmentRequiresReplacement(override.handling) ? (
                          <label className="block">
                            <span className="atlas-label">
                              Governed replacement · required
                            </span>
                            <input
                              id={`special-value-override-replacement-${variableDomToken(variable.variable)}-${variableDomToken(profile.value)}`}
                              className={`atlas-input mt-1 ${
                                override.replacementValue?.trim()
                                  ? ""
                                  : "border-amber-400 bg-amber-50"
                              }`}
                              value={override.replacementValue ?? ""}
                              onChange={(event) =>
                                onOverrideReplacement(
                                  variable.variable,
                                  profile.value,
                                  event.target.value,
                                )
                              }
                              placeholder="Valid governed value"
                            />
                          </label>
                        ) : null}
                        <textarea
                          id={`special-value-override-rationale-${variableDomToken(variable.variable)}-${variableDomToken(profile.value)}`}
                          className={`atlas-input min-h-20 min-w-72 resize-y ${
                            !override.rationale.trim()
                              ? "border-amber-400 bg-amber-50"
                              : ""
                          }`}
                          aria-label={`Override rationale for ${variable.variable} ${profile.value}`}
                          value={override.rationale}
                          onChange={(event) =>
                            onOverrideRationale(
                              variable.variable,
                              profile.value,
                              event.target.value,
                            )
                          }
                          placeholder="Required because this value overrides the variable default."
                        />
                      </div>
                    ) : policy && policyNeedsRationale ? (
                      <span
                        className={`block whitespace-normal leading-5 ${
                          policy.rationale
                            ? "text-slate-700"
                            : "font-semibold text-amber-800"
                        }`}
                      >
                        {policy.rationale ||
                          "Variable-level rationale required."}
                      </span>
                    ) : policy ? (
                      <span className="block whitespace-normal leading-5 text-slate-500">
                        Covered by the governed variable-level policy; no
                        row-level rationale required.
                      </span>
                    ) : (
                      <span className="block whitespace-normal font-semibold leading-5 text-amber-800">
                        Select a feature-level treatment before adding code-level overrides.
                      </span>
                    )}
                  </BodyCell>
                  <BodyCell>
                    <span
                      className={`inline-flex items-center gap-1 rounded-full border px-2 py-1 text-[10px] font-semibold ${
                        rowReady
                          ? "border-emerald-200 bg-emerald-50 text-emerald-800"
                          : "border-amber-200 bg-amber-50 text-amber-900"
                      }`}
                    >
                      {rowReady ? (
                        <CheckCircle2 size={12} />
                      ) : (
                        <CircleAlert size={12} />
                      )}
                      {rowReady ? "Ready" : "Treatment details required"}
                    </span>
                  </BodyCell>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function TableHeader({
  children,
  className = "",
}: {
  children: React.ReactNode;
  className?: string;
}) {
  return (
    <th
      scope="col"
      className={`border-b border-slate-800 px-3 py-3 text-left text-[10px] font-semibold uppercase tracking-wide text-slate-200 ${className}`}
    >
      {children}
    </th>
  );
}

function SortableTableHeader({
  label,
  current,
  descending,
  ascending,
  onChange,
  className = "",
}: {
  label: string;
  current: SpecialValueVariableSort;
  descending: SpecialValueVariableSort;
  ascending: SpecialValueVariableSort;
  onChange: (value: SpecialValueVariableSort) => void;
  className?: string;
}) {
  const active = current === descending || current === ascending;
  const direction: "ascending" | "descending" =
    current === ascending ? "ascending" : "descending";
  return (
    <th
      scope="col"
      aria-sort={active ? direction : "none"}
      className={`border-b border-slate-800 px-3 py-3 text-left text-[10px] font-semibold uppercase tracking-wide text-slate-200 ${className}`}
    >
      <button
        type="button"
        className="inline-flex w-full items-center justify-end gap-1 text-right hover:text-white focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-white"
        onClick={() =>
          onChange(current === descending ? ascending : descending)
        }
        title={`Sort by ${label}`}
      >
        {label}
        <span aria-hidden="true">
          {active ? (direction === "ascending" ? "↑" : "↓") : "↕"}
        </span>
      </button>
    </th>
  );
}

function BodyCell({
  children,
  className = "",
}: {
  children: React.ReactNode;
  className?: string;
}) {
  return (
    <td
      className={`border-b border-slate-100 px-3 py-3 align-top ${className}`}
    >
      {children}
    </td>
  );
}

function NumericCell({
  children,
  className = "",
}: {
  children: React.ReactNode;
  className?: string;
}) {
  return (
    <BodyCell
      className={`text-right font-medium tabular-nums text-slate-700 ${className}`}
    >
      {children}
    </BodyCell>
  );
}

function Badge({ children }: { children: React.ReactNode }) {
  return (
    <span className="rounded-full border border-slate-200 bg-slate-50 px-2.5 py-1 text-[10px] font-semibold text-slate-700">
      {children}
    </span>
  );
}

function SmallMetric({
  label,
  value,
}: {
  label: string;
  value: number;
}) {
  return (
    <div className="rounded-lg border border-slate-200 bg-slate-50 p-2.5">
      <div className="text-[9px] font-semibold uppercase tracking-wide text-slate-500">
        {label}
      </div>
      <div className="mt-1 text-xs font-semibold tabular-nums text-slate-900">
        {value.toLocaleString()}
      </div>
    </div>
  );
}

function Metric({
  label,
  value,
  tone = "neutral",
}: {
  label: string;
  value: string;
  tone?: "neutral" | "info" | "success" | "warning";
}) {
  const classes =
    tone === "success"
      ? "border-emerald-200 bg-emerald-50"
      : tone === "warning"
        ? "border-amber-200 bg-amber-50"
        : tone === "info"
          ? "border-blue-200 bg-blue-50"
          : "border-slate-200 bg-white";
  return (
    <div className={`rounded-lg border px-3 py-2 ${classes}`}>
      <div className="text-[10px] font-semibold uppercase tracking-wide text-slate-500">
        {label}
      </div>
      <div
        className="mt-1 truncate text-sm font-semibold capitalize text-slate-950"
        title={value}
      >
        {value}
      </div>
    </div>
  );
}
