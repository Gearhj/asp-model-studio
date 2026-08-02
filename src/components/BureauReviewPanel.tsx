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
  fetchBureauDetection,
  loadBureauReviewState,
  saveBureauReviewState,
  type BureauDeclaration,
  type BureauDetectionResponse,
  type BureauDetectionVariable,
  type BureauHandling,
  type BureauReviewDecision,
  type BureauReviewState,
  type BureauVariableDefault,
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

export default function BureauReviewPanel({
  target,
  eventValue,
  enabled,
  datasetIdentity,
}: {
  target: string;
  eventValue: unknown;
  enabled: boolean;
  datasetIdentity: CanonicalDatasetIdentity | null;
}) {
  const projectId = useWorkflowStore((state) => state.projectId);
  const projectName = useWorkflowStore((state) => state.projectName);
  const [state, setState] = useState<BureauReviewState>(
    loadBureauReviewState,
  );
  const [result, setResult] = useState<BureauDetectionResponse | null>(null);
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
    setLoading(true);
    setError("");
    try {
      const payload = await fetchBureauDetection({
        projectId,
        target,
        eventValue,
        state,
        metadata: bureauMetadata(),
        signal,
      });
      setResult(payload);
    } catch (cause) {
      if (cause instanceof DOMException && cause.name === "AbortError") return;
      setError(
        cause instanceof Error
          ? cause.message
          : "Credit bureau detection failed.",
      );
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
  }, [enabled, target, eventValue, state.declaration, metadataVersion]);

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
    () =>
      new Map(
        likelyVariables.map((variable) => [
          variable.variable,
          reviewStateForVariable(state, variable),
        ]),
      ),
    [likelyVariables, state],
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

  const unresolvedCount = useMemo(
    () =>
      likelyVariables.reduce(
        (total, variable) =>
          total +
          (reviewByVariable.get(variable.variable)?.unresolved ?? 0),
        0,
      ),
    [likelyVariables, reviewByVariable],
  );
  const reviewedCount = likelyVariables.filter(
    (variable) => reviewByVariable.get(variable.variable)?.reviewed,
  ).length;
  const reviewState =
    state.status === "confirmed" && unresolvedCount === 0
      ? "Confirmed"
      : unresolvedCount
        ? "Needs review"
        : "Draft ready";

  function updateState(next: BureauReviewState) {
    const draft: BureauReviewState = {
      ...next,
      status: "draft",
      evidenceStatus:
        next.evidenceStatus === "not_recorded"
          ? "not_recorded"
          : "stale",
      confirmedAt: undefined,
    };
    setState(draft);
    saveBureauReviewState(draft);
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
    setMetadataVersion((value) => value + 1);
    setMessage(`${rows.length.toLocaleString()} bureau metadata rows loaded.`);
  }

  async function persistReview(mode: "draft" | "confirmed") {
    if (!result) return;
    if (!datasetIdentity) {
      setError(
        "Credit bureau evidence requires an exact active Dataset Library version. Reactivate the registered dataset before saving this review.",
      );
      return;
    }
    if (mode === "confirmed" && unresolvedCount) {
      setError(
        `${unresolvedCount} treatment requirement${unresolvedCount === 1 ? "" : "s"} remain unresolved. Add the indicated rationale before confirmation.`,
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
    const now = new Date().toISOString();
    const nextState: BureauReviewState = {
      ...state,
      status: mode,
      evidenceStatus: mode === "confirmed" ? "ready" : "draft",
      confirmedAt: mode === "confirmed" ? now : undefined,
      savedAt: now,
    };
    try {
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
          reviewerRationale: nextState.rationale,
          reviewStatus: nextState.status,
          reviewer: "Current ATLAS user",
          reviewedAt: result.reviewed_at,
          confirmedAt: nextState.confirmedAt,
          semanticSeparation: {
            nullMissingValues: "separate",
            parseFailures: "separate",
            ordinaryOutliers: "separate",
          },
        },
      });
      setState(nextState);
      saveBureauReviewState(nextState);
      setMessage(
        mode === "confirmed"
          ? "Special-value treatment confirmed and evidence is current."
          : "Draft review saved. Evidence remains draft until confirmation.",
      );
      logDecision({
        workflowStep: "Data Acquisition",
        actionType: "workflow_setting_changed",
        subject: "Special-Value Treatment Review",
        previousValue: state.status,
        newValue: mode,
        systemRecommendation:
          "Preserve bureau special-value semantics unless a documented governed treatment requires a change.",
        followStatus:
          mode === "confirmed" ? "followed" : "not_applicable",
        userReason: state.rationale,
      });
    } catch (cause) {
      setError(
        cause instanceof Error
          ? cause.message
          : "Bureau review evidence could not be saved.",
      );
      setMessage("");
    } finally {
      setSaving(false);
    }
  }

  if (!enabled) return null;

  return (
    <section id="credit-bureau-review" className="scroll-mt-24">
      <details
        className="atlas-workflow-section atlas-workflow-section--info"
        open={!!(result?.detected || state.declaration !== "auto")}
      >
        <summary className="flex cursor-pointer list-none items-center justify-between gap-3">
          <span className="flex min-w-0 items-center gap-3">
            <span className="rounded-lg bg-blue-100 p-2 text-blue-700">
              <ShieldCheck size={18} />
            </span>
            <span>
              <span className="block text-sm font-semibold text-slate-950">
                Credit Bureau Review
              </span>
              <span className="mt-0.5 block text-xs text-slate-600">
                {loading
                  ? "Analyzing full-population bureau signals"
                  : result?.detected
                    ? `${result.likely_variable_count} bureau variables · ${result.rows_with_special_values.toLocaleString()} rows with special values · ${reviewState}`
                    : "No bureau data confirmed; manual declaration remains available"}
              </span>
            </span>
          </span>
          <span className="flex items-center gap-2">
            {result ? (
              <AtlasDataScopeBadge
                scope="full_dataset"
                rows={result.row_count}
              />
            ) : null}
            <ChevronDown size={17} />
          </span>
        </summary>

        <div className="mt-4 space-y-4 border-t border-blue-200 pt-4">
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
                className="grid gap-2 sm:grid-cols-2 xl:grid-cols-5"
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
                  className="rounded-xl border border-amber-200 bg-amber-50/40 p-4"
                  data-testid="special-value-treatment-review"
                >
                  <div className="flex flex-col gap-2 lg:flex-row lg:items-start lg:justify-between">
                    <div>
                      <div className="text-[10px] font-semibold uppercase tracking-wide text-amber-800">
                        Governed data-quality contract
                      </div>
                      <h3 className="mt-1 text-base font-semibold text-slate-950">
                        Special-Value Treatment Review
                      </h3>
                      <p className="mt-1 max-w-4xl text-xs leading-5 text-slate-600">
                        Select one variable-level default, then add only
                        necessary value-level overrides. Bureau special values
                        remain distinct from null missing values, parse
                        failures, and ordinary outliers.
                      </p>
                      <p
                        className="mt-2 max-w-4xl rounded-lg border border-amber-200 bg-white px-3 py-2 text-xs font-medium leading-5 text-slate-700"
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
                          ? "border-amber-300 bg-white text-amber-900"
                          : "border-emerald-200 bg-emerald-50 text-emerald-800"
                      }`}
                    >
                      {unresolvedCount
                        ? `${unresolvedCount} unresolved`
                        : "All policies reviewable"}
                    </span>
                  </div>

                  <div className="mt-4 grid gap-4 xl:grid-cols-[280px_minmax(0,1fr)]">
                    <aside className="rounded-xl border border-slate-200 bg-white p-3">
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
                                  ? "border-blue-500 bg-blue-50 ring-1 ring-blue-100"
                                  : "border-slate-200 bg-white hover:border-blue-200"
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
                {unresolvedCount
                  ? `${unresolvedCount} rationale requirement${unresolvedCount === 1 ? "" : "s"} remain. Draft saving is available; confirmation is blocked.`
                  : state.status === "confirmed"
                    ? "The treatment contract and supporting evidence are current."
                    : "All treatment rows are resolved. Confirm when the review is complete."}
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
                disabled={!result || saving}
              >
                <Save size={15} /> Save Draft Review
              </button>
              <button
                type="button"
                className="atlas-primary-button"
                onClick={() => void persistReview("confirmed")}
                disabled={!result || saving || unresolvedCount > 0}
                title={
                  unresolvedCount
                    ? "Resolve the indicated rationale requirements before confirmation."
                    : "Persist the governed treatment and current evidence."
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
  onDefault,
  onOverride,
  onOverrideRationale,
}: {
  variable: BureauDetectionVariable;
  state: BureauReviewState;
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
                  reviewed.reviewed
                    ? "border-emerald-200 bg-emerald-50 text-emerald-800"
                    : "border-amber-200 bg-amber-50 text-amber-900"
                }`}
              >
                {reviewed.reviewed ? "Reviewed" : "Review required"}
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
                  <NumericCell className="text-sm font-semibold text-slate-950">
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
                    <span className="inline-flex max-w-full whitespace-normal rounded-full border border-blue-100 bg-blue-50 px-2.5 py-1 text-[10px] font-semibold leading-4 text-blue-900">
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
