import { useEffect, useMemo, useState } from "react";
import {
  CheckCircle2,
  ChevronDown,
  CircleAlert,
  FileUp,
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
  bureauMetadata,
  assertSpecialValueReviewContract,
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
import { parseBureauMetadataCsv, saveBureauMetadata } from "../lib/creditBureau";
import { createEvidence } from "../lib/evidenceGraph";
import {
  buildCanonicalEvidenceEnvelope,
  type CanonicalDatasetIdentity,
} from "../lib/datasetIdentity";
import { logDecision } from "../lib/decisionJournal";
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

function treatmentRequiresRationale(
  handling: BureauHandling,
  override: boolean,
) {
  return override || destructiveTreatments.has(handling);
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
  const policy = defaultDecision(state, variable.variable);
  const defaultReady =
    !treatmentRequiresRationale(policy.handling, false) ||
    !!policy.rationale.trim();
  const unresolvedRows = variable.special_values.filter((profile) => {
    const override = valueOverride(
      state,
      variable.variable,
      profile.value,
    );
    if (!override) return false;
    return (
      treatmentRequiresRationale(override.handling, true) &&
      !override.rationale.trim()
    );
  }).length;
  return {
    reviewed: defaultReady && unresolvedRows === 0,
    unresolved: (defaultReady ? 0 : 1) + unresolvedRows,
    handling: policy.handling,
  };
}

function pct(value: number | null | undefined, digits = 2) {
  return typeof value === "number" && Number.isFinite(value)
    ? `${(value * 100).toFixed(digits)}%`
    : "Not available";
}

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
  error?: boolean;
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
  };
}

function stateFromDurableReview(
  previous: BureauReviewState,
  review: SpecialValueReviewContract,
): BureauReviewState {
  const now = review.updated_at ?? new Date().toISOString();
  return {
    ...previous,
    rationale: review.reviewer_rationale,
    variableDefaults: review.variable_decisions.map((decision) => ({
      variable: decision.variable,
      handling: decision.policy,
      rationale: decision.rationale,
      updatedAt: now,
    })),
    decisions: review.variable_decisions.flatMap((decision) =>
      decision.overrides.map((override) => ({
        variable: decision.variable,
        value: Number(override.value),
        handling: override.policy,
        rationale: override.rationale,
        updatedAt: now,
        override: true as const,
      })),
    ),
    status: "draft",
    evidenceStatus: review.status === "confirmed" ? "ready" : "draft",
    confirmedAt: undefined,
    savedAt: review.updated_at ?? undefined,
    draftAuthority: specialValueDraftAuthority(review),
  };
}

export default function BureauReviewPanel({
  target,
  eventValue,
  enabled,
  datasetIdentity,
  onReviewStatus,
}: {
  target: string;
  eventValue: unknown;
  enabled: boolean;
  datasetIdentity: CanonicalDatasetIdentity | null;
  onReviewStatus?: (status: BureauReviewPanelStatus) => void;
}) {
  const projectId = useWorkflowStore((state) => state.projectId);
  const projectName = useWorkflowStore((state) => state.projectName);
  const [state, setState] = useState<BureauReviewState>(
    loadBureauReviewState,
  );
  const [result, setResult] = useState<BureauDetectionResponse | null>(null);
  const [durableReview, setDurableReview] =
    useState<SpecialValueReviewContract | null>(null);
  const [draftDirty, setDraftDirty] = useState(false);
  const [selectedVariable, setSelectedVariable] = useState("");
  const [variableSearch, setVariableSearch] = useState("");
  const [reviewFilter, setReviewFilter] = useState<
    "all" | "reviewed" | "unreviewed"
  >("all");
  const [treatmentFilter, setTreatmentFilter] = useState<
    "all" | BureauHandling
  >("all");
  const [variableSort, setVariableSort] = useState<
    "prevalence_desc" | "prevalence_asc" | "name"
  >("prevalence_desc");
  const [loading, setLoading] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");
  const [metadataVersion, setMetadataVersion] = useState(0);

  async function runDetection(signal?: AbortSignal) {
    if (!enabled) return;
    if (!datasetIdentity) {
      setResult(null);
      setError(
        "Credit bureau detection requires the exact active Dataset Library version. Reload Data Acquisition and retry.",
      );
      return;
    }
    setLoading(true);
    setError("");
    setResult(null);
    setDurableReview(null);
    try {
      const payload = await fetchBureauDetection({
        projectId,
        datasetIdentity,
        target,
        eventValue,
        state,
        metadata: bureauMetadata(),
        signal,
      });
      const lineage = exactReviewLineage(payload, datasetIdentity, projectId);
      assertSpecialValueReviewContract(payload.special_value_review, lineage);
      const exactReview = await fetchSpecialValueReview({ lineage, signal });
      if (signal?.aborted) return;
      setResult(payload);
      setDurableReview(exactReview);
      setState((previous) => {
        const hydrated = stateFromDurableReview(previous, exactReview);
        saveBureauReviewState(hydrated);
        return hydrated;
      });
      setDraftDirty(false);
    } catch (cause) {
      if (cause instanceof DOMException && cause.name === "AbortError") return;
      setError(
        cause instanceof Error
          ? cause.message
          : "Credit bureau detection failed.",
      );
      setResult(null);
      setDurableReview(null);
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
    metadataVersion,
    datasetIdentity?.dataset_id,
    datasetIdentity?.dataset_version_id,
    datasetIdentity?.activation_revision,
  ]);

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

  useEffect(() => {
    if (
      likelyVariables.length &&
      !likelyVariables.some((row) => row.variable === selectedVariable)
    ) {
      setSelectedVariable(likelyVariables[0].variable);
    }
  }, [likelyVariables, selectedVariable]);

  useEffect(() => {
    if (!likelyVariables.length) return;
    const missingDefaults = likelyVariables.filter(
      (variable) =>
        !state.variableDefaults.some(
          (row) => row.variable === variable.variable,
        ),
    );
    if (!missingDefaults.length) return;
    const now = new Date().toISOString();
    const next: BureauReviewState = {
      ...state,
      variableDefaults: [
        ...state.variableDefaults,
        ...missingDefaults.map((variable) => ({
          variable: variable.variable,
          handling: "preserve_informative" as const,
          rationale: "",
          updatedAt: now,
        })),
      ],
      status: "draft",
      evidenceStatus:
        state.evidenceStatus === "not_recorded"
          ? "not_recorded"
          : "stale",
      confirmedAt: undefined,
    };
    setState(next);
    saveBureauReviewState(next);
  }, [likelyVariables, state]);

  const reviewByVariable = useMemo(
    () => {
      const durablyReviewed = new Set(
        durableReview?.variable_decisions.map((decision) => decision.variable) ?? [],
      );
      return (
      new Map(
        likelyVariables.map((variable) => [
          variable.variable,
          {
            ...reviewStateForVariable(state, variable),
            reviewed: durablyReviewed.has(variable.variable),
          },
        ]),
      )
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
          `${variable.variable} ${variable.reasons.join(" ")}`
            .toLowerCase()
            .includes(normalized),
      )
      .filter((variable) => {
        const review = reviewByVariable.get(variable.variable);
        if (reviewFilter === "reviewed") return review?.reviewed;
        if (reviewFilter === "unreviewed") return !review?.reviewed;
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
        if (variableSort === "name") {
          return left.variable.localeCompare(right.variable);
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
    likelyVariables.find((row) => row.variable === selectedVariable) ??
    filteredVariables[0] ??
    null;

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
      error: Boolean(error),
    });
  }, [
    draftDirty,
    durableReview,
    error,
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
    saveBureauReviewState(draft);
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
        defaultDecision(state, variable).handling,
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

  async function uploadMetadata(file: File) {
    const rows = parseBureauMetadataCsv(await file.text());
    if (!rows.length) {
      setMessage(
        "No valid bureau metadata rows were found in the selected CSV.",
      );
      return;
    }
    saveBureauMetadata(rows);
    setResult(null);
    setDurableReview(null);
    setDraftDirty(true);
    setMetadataVersion((value) => value + 1);
    setMessage(`${rows.length.toLocaleString()} bureau metadata rows loaded.`);
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
    setMessage(
      mode === "confirmed"
        ? "Confirming the governed special-value treatment..."
        : "Saving the draft special-value review...",
    );
    const lineage = exactReviewLineage(result, datasetIdentity, projectId);
    const variableDecisions: SpecialValueReviewVariableDecision[] =
      likelyVariables.map((variable) => {
        const policy = defaultDecision(state, variable.variable);
        return {
          variable: variable.variable,
          policy: policy.handling,
          rationale: policy.rationale.trim(),
          overrides: state.decisions
            .filter((decision) => decision.variable === variable.variable)
            .map((decision) => ({
              value: decision.value,
              policy: decision.handling,
              rationale: decision.rationale.trim(),
            })),
        };
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
      saveBureauReviewState(nextState);
      setDraftDirty(false);
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
      await createEvidence({
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
        sourceRoute: "/step01?section=credit-bureau-review",
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
        status: mode === "confirmed" ? "ready" : "draft",
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
          reviewer: "Current ATLAS user",
          reviewedAt: result.reviewed_at,
          confirmedAt: savedReview.confirmed_at,
          semanticSeparation: {
            nullMissingValues: "separate",
            parseFailures: "separate",
            ordinaryOutliers: "separate",
          },
        },
      });
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
      setError(
        `Durable special-value review revision ${savedReview.revision} was saved, but supporting evidence could not be updated. ${cause instanceof Error ? cause.message : "Retry evidence creation."}`,
      );
      setMessage(
        `The backend review remains authoritative at revision ${savedReview.revision}.`,
      );
    } finally {
      setSaving(false);
    }
  }

  if (!enabled) return null;

  return (
    <section id="credit-bureau-review" className="scroll-mt-24">
      <details
        className="overflow-hidden rounded-xl border-2 border-indigo-800 bg-indigo-50/50 shadow-[0_16px_36px_rgba(30,41,99,0.14)]"
        open={!!(result?.detected || state.declaration !== "auto")}
        data-testid="special-value-decision-workspace"
      >
        <summary className="flex cursor-pointer list-none items-center justify-between gap-3 bg-gradient-to-r from-slate-950 via-indigo-950 to-indigo-900 px-5 py-4 text-white focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-[-3px] focus-visible:outline-white">
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
                  : result?.detected
                    ? `${result.likely_variable_count} bureau variables · ${reviewedCount} reviewed · ${unresolvedCount} unresolved requirements`
                    : "No bureau data confirmed; manual declaration remains available"}
              </span>
            </span>
          </span>
          <span className="flex items-center gap-2">
            {result ? (
              <span className="rounded-full border border-indigo-300/50 bg-white/10 px-3 py-1 text-xs font-semibold text-indigo-50">
                {reviewState}
              </span>
            ) : null}
            <ChevronDown size={17} className="text-indigo-100" />
          </span>
        </summary>

        <div className="space-y-4 bg-gradient-to-b from-indigo-50/80 to-white p-5">
          <div className="flex flex-wrap items-center justify-between gap-3 rounded-lg border border-indigo-200 bg-white px-3 py-2">
            <div className="text-xs font-medium text-slate-700">
              Bureau special values remain separate from true nulls, parse failures, and ordinary outliers.
            </div>
            {result ? <AtlasDataScopeBadge scope="full_dataset" rows={result.row_count} /> : null}
          </div>
          <div className="grid gap-3 lg:grid-cols-[minmax(240px,340px)_1fr_auto] lg:items-end">
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
            <label className="atlas-secondary-button cursor-pointer">
              <FileUp size={15} /> Upload metadata CSV
              <input
                className="hidden"
                type="file"
                accept=".csv,text/csv"
                onChange={(event) =>
                  event.target.files?.[0] &&
                  void uploadMetadata(event.target.files[0])
                }
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
                  label="Review state"
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
                        Review each detected variable and its observed special codes
                      </h3>
                      <p className="mt-1 max-w-4xl text-xs leading-5 text-indigo-100">
                        Select one variable-level default, then add only
                        necessary value-level overrides. Bureau special values
                        remain distinct from null missing values, parse
                        failures, and ordinary outliers.
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
                    <span
                      className={`rounded-full border px-3 py-1 text-xs font-semibold ${
                        unresolvedCount
                          ? "border-amber-300 bg-amber-100 text-amber-950"
                          : "border-emerald-300 bg-emerald-100 text-emerald-900"
                      }`}
                    >
                      {unresolvedCount
                        ? `${unresolvedCount} unresolved`
                        : "All policies reviewable"}
                    </span>
                  </div>

                  <div className="grid gap-4 p-4 xl:grid-cols-[280px_minmax(0,1fr)]">
                    <aside className="sticky top-24 self-start rounded-xl border border-indigo-200 bg-white p-3 shadow-sm">
                      <div className="flex items-center gap-2 text-sm font-semibold text-slate-950">
                        <Filter size={15} className="text-blue-700" />
                        Variable navigator
                      </div>
                      <label className="relative mt-3 block">
                        <span className="sr-only">Search bureau variables</span>
                        <Search
                          size={14}
                          className="pointer-events-none absolute left-3 top-2.5 text-slate-400"
                        />
                        <input
                          className="atlas-input pl-9"
                          value={variableSearch}
                          onChange={(event) =>
                            setVariableSearch(event.target.value)
                          }
                          placeholder="Search variables"
                        />
                      </label>
                      <div className="mt-2 grid grid-cols-2 gap-2">
                        <label>
                          <span className="atlas-label">Review</span>
                          <select
                            className="atlas-input mt-1"
                            value={reviewFilter}
                            onChange={(event) =>
                              setReviewFilter(
                                event.target.value as
                                  | "all"
                                  | "reviewed"
                                  | "unreviewed",
                              )
                            }
                          >
                            <option value="all">All</option>
                            <option value="reviewed">Reviewed</option>
                            <option value="unreviewed">Unreviewed</option>
                          </select>
                        </label>
                        <label>
                          <span className="atlas-label">Sort</span>
                          <select
                            className="atlas-input mt-1"
                            value={variableSort}
                            onChange={(event) =>
                              setVariableSort(
                                event.target.value as
                                  | "prevalence_desc"
                                  | "prevalence_asc"
                                  | "name",
                              )
                            }
                          >
                            <option value="prevalence_desc">
                              Prevalence · high
                            </option>
                            <option value="prevalence_asc">
                              Prevalence · low
                            </option>
                            <option value="name">Variable name</option>
                          </select>
                        </label>
                      </div>
                      <label className="mt-2 block">
                        <span className="atlas-label">
                          Treatment action
                        </span>
                        <select
                          className="atlas-input mt-1"
                          value={treatmentFilter}
                          onChange={(event) =>
                            setTreatmentFilter(
                              event.target.value as
                                | "all"
                                | BureauHandling,
                            )
                          }
                        >
                          <option value="all">All treatment actions</option>
                          {Object.entries(handlingLabels).map(
                            ([value, label]) => (
                              <option key={value} value={value}>
                                {label}
                              </option>
                            ),
                          )}
                        </select>
                      </label>
                      <div className="mt-3 max-h-[520px] space-y-1 overflow-auto pr-1">
                        {filteredVariables.map((variable) => {
                          const review = reviewByVariable.get(
                            variable.variable,
                          );
                          const active =
                            activeVariable?.variable === variable.variable;
                          return (
                            <button
                              key={variable.variable}
                              type="button"
                              className={`w-full rounded-lg border p-3 text-left transition ${
                                active
                                  ? "border-violet-500 bg-violet-50 ring-1 ring-violet-100"
                                  : "border-slate-200 bg-white hover:border-violet-200"
                              }`}
                              onClick={() =>
                                setSelectedVariable(variable.variable)
                              }
                            >
                              <span className="block break-words text-xs font-semibold text-slate-950">
                                {variable.variable}
                              </span>
                              <span className="mt-1 flex items-center justify-between gap-2 text-[10px] text-slate-500">
                                <span>
                                  {pct(variable.special_value_frequency)}
                                </span>
                                <span
                                  className={
                                    review?.reviewed
                                      ? "font-semibold text-emerald-700"
                                      : "font-semibold text-amber-700"
                                  }
                                >
                                  {review?.reviewed
                                    ? "Reviewed"
                                    : "Needs review"}
                                </span>
                              </span>
                            </button>
                          );
                        })}
                        {!filteredVariables.length ? (
                          <div className="rounded-lg border border-dashed border-slate-200 p-4 text-center text-xs text-slate-500">
                            No variables match these filters.
                          </div>
                        ) : null}
                      </div>
                    </aside>

                    {activeVariable ? (
                      <VariableTreatmentWorkspace
                        variable={activeVariable}
                        state={state}
                        durableReviewed={Boolean(
                          durableReview?.variable_decisions.some(
                            (decision) =>
                              decision.variable === activeVariable.variable,
                          ),
                        )}
                        onDefault={updateVariableDefault}
                        onOverride={updateOverride}
                        onOverrideRationale={updateOverrideRationale}
                      />
                    ) : (
                      <div className="rounded-xl border border-dashed border-slate-300 bg-white p-8 text-center text-sm text-slate-500">
                        Select a bureau variable to review its governed
                        special-value table.
                      </div>
                    )}
                  </div>
                </div>
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
                    ? "Resolve the indicated rationale requirements before confirmation."
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
          </div>
        </div>
      </details>
    </section>
  );
}

function VariableTreatmentWorkspace({
  variable,
  state,
  durableReviewed,
  onDefault,
  onOverride,
  onOverrideRationale,
}: {
  variable: BureauDetectionVariable;
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
}) {
  const policy = defaultDecision(state, variable.variable);
  const policyNeedsRationale = treatmentRequiresRationale(
    policy.handling,
    false,
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
                className="atlas-input mt-1"
                value={policy.handling}
                onChange={(event) =>
                  onDefault(variable.variable, {
                    handling: event.target.value as BureauHandling,
                  })
                }
              >
                {selectableHandlingEntries(policy.handling).map((option) => (
                  <option key={option.value} value={option.value}>
                    {option.label}
                  </option>
                ))}
              </select>
              <span
                className="mt-1 block text-xs leading-5 text-slate-600"
                data-testid="selected-special-value-treatment-help"
              >
                {handlingHelp[policy.handling]}
              </span>
            </label>
            {policyNeedsRationale ? (
              <label>
                <span className="atlas-label">
                  Variable-level rationale · required
                </span>
                <textarea
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
            ) : (
              <div className="rounded-lg border border-emerald-100 bg-emerald-50 px-3 py-2 text-xs leading-5 text-emerald-900">
                This governed default applies to every compatible row. A
                separate rationale is needed only for an override or
                destructive treatment.
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

      <div
        className="max-w-full overflow-auto rounded-xl border border-slate-200 bg-white shadow-sm"
        data-testid="special-value-treatment-table"
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
                Event count
              </TableHeader>
              <TableHeader className="w-28 text-right">
                Event rate
              </TableHeader>
              <TableHeader className="w-36 text-right">
                Regular-value event rate
              </TableHeader>
              <TableHeader className="w-36 text-right">
                Event-rate difference
              </TableHeader>
              <TableHeader className="w-56">Default action</TableHeader>
              <TableHeader className="w-64">
                Override action
              </TableHeader>
              <TableHeader className="w-80">Rationale</TableHeader>
              <TableHeader className="w-32">Review state</TableHeader>
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
                override?.handling ?? policy.handling;
              const rationaleRequired = treatmentRequiresRationale(
                effectiveHandling,
                !!override,
              );
              const rationale = override?.rationale ?? policy.rationale;
              const rowReady =
                !rationaleRequired || !!rationale.trim();
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
                      {handlingLabels[policy.handling]}
                    </span>
                  </BodyCell>
                  <BodyCell>
                    <div className="flex items-center gap-2">
                      <select
                        className="atlas-input min-w-52"
                        aria-label={`Override handling for ${variable.variable} ${profile.value}`}
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
                          override?.handling ?? policy.handling,
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
                      <textarea
                        className={`atlas-input min-h-20 min-w-72 resize-y ${
                          !rowReady
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
                    ) : policyNeedsRationale ? (
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
                    ) : (
                      <span className="block whitespace-normal leading-5 text-slate-500">
                        Covered by the governed variable-level policy; no
                        row-level rationale required.
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
                      {rowReady ? "Ready" : "Rationale required"}
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
      className={`border-b border-slate-800 px-3 py-3 text-left text-[10px] font-semibold uppercase tracking-wide text-slate-200 ${className}`}
    >
      {children}
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
