import { useEffect, useMemo, useRef, useState } from "react";
import type { EChartsOption } from "echarts";
import {
  AlertTriangle,
  ArrowDown,
  ArrowUp,
  ChevronLeft,
  ChevronRight,
  Copy,
  Eye,
  FlaskConical,
  Layers3,
} from "lucide-react";
import EChartsPanel from "../../visual-intelligence/EChartsPanel";
import type { CurrentGoldReviewState } from "../workflow/currentGoldDataReview";
import { CockpitDrawer } from "./CockpitDrawer";
import { useCockpitStore } from "./cockpitApi";
import {
  downloadAggregatedCsv,
  useProjectEdaMetadata,
  type ProjectEdaFilters,
} from "./projectEdaApi";
import {
  type ImputationMethod,
  type MissingDetail,
  type MissingOverride,
  type MissingSummary,
  type MissingTableRow,
  type PaginatedTreatmentTable,
  type PredictedPreview,
  type TreatmentPolicy,
  fetchAllTreatmentRows,
  useTreatmentGet,
  useTreatmentMutation,
  useTreatmentPost,
} from "./projectTreatmentApi";
import {
  DownloadAggregatedButton,
  GovernedPriorAuthorityCard,
  type StudioFilterState,
  StudioRequestState,
  TreatmentDecisionHeader,
  TreatmentMetric,
  TreatmentPolicyActions,
  TreatmentStudioFilters,
  TreatmentStudioShell,
  canonicalPolicySignature,
  formatInteger,
  formatPercent,
  formatValue,
  useGovernedPriorAuthority,
} from "./TreatmentStudioShell";

const METHODS: { value: ImputationMethod; label: string; detail: string }[] = [
  {
    value: "RETAIN_WITH_INDICATOR",
    label: "Retain missing + indicator",
    detail: "Leave physical value missing and preserve an explicit indicator.",
  },
  {
    value: "MEAN",
    label: "Mean",
    detail: "Training-fold mean; continuous only.",
  },
  {
    value: "MEDIAN",
    label: "Median",
    detail: "Training-fold median; numeric or ordered numeric.",
  },
  {
    value: "MODE",
    label: "Mode",
    detail: "Training-fold most frequent value.",
  },
  {
    value: "CONSTANT",
    label: "Constant · advanced",
    detail: "Explicit validated value.",
  },
  {
    value: "GOVERNED_PRIOR",
    label: "Hierarchical / league prior",
    detail: "Only when a registered point-in-time prior contract exists.",
  },
  {
    value: "PREDICTED",
    label: "Predicted value",
    detail: "Explicit chronological cross-fitted preprocessing preview.",
  },
  {
    value: "UNKNOWN_CATEGORY",
    label: "Explicit UNKNOWN category",
    detail: "Nominal categorical fields only.",
  },
  {
    value: "DROP_VARIABLE",
    label: "Drop variable",
    detail: "Explicit candidate-library decision.",
  },
  {
    value: "EXCLUDE_ROW",
    label: "Exclude row · advanced/high risk",
    detail: "Shows exact population loss; never automatic.",
  },
];
const DEFAULT_OVERRIDE: MissingOverride = {
  method: "MEDIAN",
  retainIndicator: true,
  coldStartMethod: "RETAIN_WITH_INDICATOR",
  sourceFailureMethod: "REVIEW_REQUIRED",
  notes: "",
};
const PAGE_SIZE = 30;
const PREDICTED_PREVIEW_SEED = 731026;
const PREDICTED_PREVIEW_DESIGN = "CHRONOLOGICAL_GAME_GROUPED_CROSS_FIT";

function predictedPreviewMatchesRequest(
  preview: PredictedPreview | null | undefined,
  variable: string,
  predictorSet: string[],
  seed: number,
): preview is PredictedPreview {
  return Boolean(
    preview &&
      preview.status === "COMPLETE" &&
      preview.variable === variable &&
      preview.seed === seed &&
      preview.eligiblePredictors.length === predictorSet.length &&
      preview.eligiblePredictors.every(
        (predictor, index) => predictor === predictorSet[index],
      ),
  );
}
const MISSING_COLUMNS: {
  label: string;
  field: keyof MissingTableRow | null;
}[] = [
  { label: "NUMBER OF MISSING VALUES", field: "numberOfMissingValues" },
  { label: "VARIABLE", field: "variable" },
  { label: "MISSING %", field: "missingPercent" },
  { label: "DEVELOPMENT N", field: "developmentN" },
  { label: "OBSERVED N", field: "observedN" },
  { label: "DATA TYPE", field: "dataType" },
  { label: "FEATURE FAMILY", field: "featureFamily" },
  { label: "PRIMARY MISSINGNESS REASON", field: "primaryReason" },
  { label: "NO-PRIOR-HISTORY COUNT", field: "noPriorHistoryCount" },
  { label: "INSUFFICIENT-HISTORY COUNT", field: "insufficientHistoryCount" },
  { label: "SOURCE-UNAVAILABLE COUNT", field: "sourceUnavailableCount" },
  { label: "COMPUTATION-FAILURE COUNT", field: "computationFailureCount" },
  {
    label: "PAIRED MISSINGNESS INDICATOR",
    field: "pairedMissingnessIndicator",
  },
  { label: "SELECTED IMPUTATION METHOD", field: "selectedImputationMethod" },
  { label: "IMPUTED VALUE / POLICY", field: "imputedValueOrPolicy" },
  { label: "ELIGIBLE METHODS", field: null },
  { label: "AFFECTED GAMES", field: "affectedGames" },
  { label: "AFFECTED BATTERS", field: "affectedBatters" },
  { label: "AFFECTED PITCHERS", field: "affectedPitchers" },
  { label: "STATUS", field: "status" },
  { label: "VIEW DETAILS", field: null },
];

function authorityKey(state: CurrentGoldReviewState): string {
  const review = state.review;
  return review
    ? [
        review.sourceAuthority.manifestSha,
        review.goldAuthority.manifestSha,
        review.contextualFeaturePack?.manifestSha256 ?? "no-context",
        review.reviewDigest,
      ].join(":")
    : "authority-pending";
}
function methodLabel(method: string | null | undefined): string {
  return METHODS.find((item) => item.value === method)?.label ?? method ?? "—";
}

function familyCompatibilityFailure(
  row: MissingTableRow,
  override: MissingOverride,
): string | null {
  if (!row.eligible) {
    return row.exclusionReason || "destination variable is read-only metadata";
  }
  if (!row.eligibleMethods.includes(override.method)) {
    return `${methodLabel(override.method)} is not eligible for the destination variable`;
  }
  if (override.method === "CONSTANT") {
    return "constant values require destination-specific type and domain validation";
  }
  if (override.method === "PREDICTED") {
    return "predicted imputation requires a destination-specific predictor contract and preview";
  }
  if (
    override.coldStartMethod === "GOVERNED_PRIOR_WITH_INDICATOR" &&
    !row.governedPriorAvailable
  ) {
    return (
      row.governedPriorUnavailableReason ||
      "no registered governed-prior authority exists for the destination variable"
    );
  }
  return null;
}

function sanitizeColdStartOverrides(
  overrides: Record<string, MissingOverride>,
  governedPriorEligibleVariables: string[],
): Record<string, MissingOverride> {
  const eligible = new Set(governedPriorEligibleVariables);
  return Object.fromEntries(
    Object.entries(overrides).map(([variable, override]) => [
      variable,
      override.coldStartMethod === "GOVERNED_PRIOR_WITH_INDICATOR" &&
      !eligible.has(variable)
        ? { ...override, coldStartMethod: "RETAIN_WITH_INDICATOR" }
        : override,
    ]),
  );
}

function missingPolicyControlSignature(
  globalMethod: string,
  overrides: Record<string, MissingOverride>,
  notes: string,
): string {
  return canonicalPolicySignature({
    globalMethod,
    overrides: Object.fromEntries(
      Object.entries(overrides).map(([variable, override]) => [
        variable,
        {
          method: override.method,
          constantValue: override.constantValue,
          retainIndicator: override.retainIndicator,
          coldStartMethod: override.coldStartMethod,
          sourceFailureMethod: override.sourceFailureMethod,
          predictorSet: override.predictorSet,
          seed: override.seed,
          notes: override.notes,
        },
      ]),
    ),
    notes: notes.trim(),
  });
}

function parseHandoff(
  raw: string | undefined,
  pendingRaw: string | undefined,
  key: string,
): {
  selectedVariables: string[];
  filters: ProjectEdaFilters;
  pendingVariables: string[];
  outcomeFilterRemoved: boolean;
} {
  let selectedVariables: string[] = [];
  let filters: ProjectEdaFilters = {};
  let pendingVariables: string[] = [];
  let outcomeFilterRemoved = false;
  try {
    const value = raw
      ? (JSON.parse(raw) as {
          destination?: string;
          authorityKey?: string;
          selectedVariables?: string[];
          filters?: ProjectEdaFilters;
        })
      : null;
    if (value?.destination === "missing" && value.authorityKey === key) {
      selectedVariables = value.selectedVariables ?? [];
      const { outcomes, ...safeFilters } = value.filters ?? {};
      filters = safeFilters;
      outcomeFilterRemoved = Boolean(outcomes?.length);
    }
  } catch {
    /* malformed handoff is ignored */
  }
  try {
    const pending = pendingRaw
      ? (JSON.parse(pendingRaw) as {
          authorityKey?: string;
          variable?: string;
          requirements?: { variable?: string }[];
        })
      : null;
    if (pending?.authorityKey === key) {
      pendingVariables = [
        ...new Set(
          [
            pending.variable,
            ...(pending.requirements ?? []).map((item) => item.variable),
          ].filter((variable): variable is string => Boolean(variable)),
        ),
      ];
      selectedVariables = [
        ...new Set([...selectedVariables, ...pendingVariables]),
      ];
    }
  } catch {
    /* malformed handoff is ignored */
  }
  return {
    selectedVariables,
    filters,
    pendingVariables,
    outcomeFilterRemoved,
  };
}

function missingDistributionOption(
  detail: MissingDetail,
  after: boolean,
): EChartsOption {
  const distribution = after ? detail.after : detail.before;
  if (distribution.categories) {
    return {
      animationDuration: 220,
      color: ["#0891b2", "#f59e0b"],
      grid: { left: 112, right: 18, top: 30, bottom: 35, containLabel: true },
      tooltip: { trigger: "axis", confine: true },
      legend: { top: 0 },
      xAxis: { type: "value", name: "Rows" },
      yAxis: {
        type: "category",
        data: distribution.categories.map((row) => row.value),
      },
      series: [
        {
          name: "Original observations",
          type: "bar",
          stack: "rows",
          data: distribution.categories.map((row) =>
            Math.max(0, row.count - Number(row.imputedCount ?? 0)),
          ),
        },
        {
          name: "Imputed preview",
          type: "bar",
          stack: "rows",
          data: distribution.categories.map((row) => row.imputedCount ?? 0),
          itemStyle: {
            decal: {
              symbol: "rect",
              dashArrayX: [4, 2],
              dashArrayY: [2, 3],
              color: "rgba(255,255,255,.55)",
            },
          },
        },
      ],
    };
  }
  const histogram = distribution.histogram ?? [];
  return {
    animationDuration: 220,
    color: ["#0891b2", "#f59e0b"],
    grid: { left: 48, right: 18, top: 30, bottom: 48, containLabel: true },
    tooltip: { trigger: "axis", confine: true },
    legend: { top: 0 },
    xAxis: {
      type: "category",
      data: histogram.map(
        (row) =>
          `${formatValue(row.binStart, 3)}–${formatValue(row.binEnd, 3)}`,
      ),
      axisLabel: { rotate: 35, hideOverlap: true },
    },
    yAxis: { type: "value", name: "Rows" },
    series: [
      {
        name: "Original observations",
        type: "bar",
        stack: "rows",
        data: histogram.map((row) =>
          Math.max(0, row.count - Number(row.imputedCount ?? 0)),
        ),
      },
      {
        name: "Imputed preview",
        type: "bar",
        stack: "rows",
        data: histogram.map((row) => row.imputedCount ?? 0),
        itemStyle: {
          decal: {
            symbol: "rect",
            dashArrayX: [4, 2],
            dashArrayY: [2, 3],
            color: "rgba(255,255,255,.55)",
          },
        },
      },
    ],
  };
}

function predictedDistributionOption(preview: PredictedPreview): EChartsOption {
  const values = preview.predictedDistribution;
  if (values.length && "binStart" in values[0]) {
    const bins = values as Array<{
      binStart: number;
      binEnd: number;
      count: number;
    }>;
    return {
      animationDuration: 180,
      grid: { left: 48, right: 18, top: 24, bottom: 42, containLabel: true },
      tooltip: { trigger: "axis", confine: true },
      xAxis: {
        type: "category",
        data: bins.map(
          (row) =>
            `${formatValue(row.binStart, 3)}–${formatValue(row.binEnd, 3)}`,
        ),
        axisLabel: { rotate: 30, hideOverlap: true },
      },
      yAxis: { type: "value", name: "OOF imputed rows" },
      series: [
        {
          type: "bar",
          data: bins.map((row) => row.count),
          itemStyle: { color: "#7c3aed" },
        },
      ],
    };
  }
  const categories = values as Array<{ value: string; count: number }>;
  return {
    animationDuration: 180,
    grid: { left: 100, right: 18, top: 24, bottom: 32, containLabel: true },
    tooltip: { trigger: "axis", confine: true },
    xAxis: { type: "value", name: "OOF imputed rows" },
    yAxis: { type: "category", data: categories.map((row) => row.value) },
    series: [
      {
        type: "bar",
        data: categories.map((row) => row.count),
        itemStyle: { color: "#7c3aed" },
      },
    ],
  };
}

function PredictedPreviewPanel({
  detail,
  preview,
  status,
  error,
  run,
}: {
  detail: MissingDetail;
  preview: PredictedPreview | null;
  status: string;
  error: string | null;
  run: () => void;
}) {
  return (
    <section
      className="rounded-2xl border border-violet-200 bg-violet-50/40 p-4"
      data-testid="stage3-predicted-imputation-preview"
    >
      <div className="flex flex-wrap items-start gap-3">
        <div>
          <div className="text-[10px] font-semibold uppercase tracking-[0.14em] text-violet-800">
            Preprocessing preview
          </div>
          <h4 className="mt-1 font-semibold text-slate-950">
            Leakage-safe predicted imputation
          </h4>
          <p className="mt-1 text-xs leading-5 text-slate-600">
            One imputer per variable and chronological training fold. The
            outcome, same-game future evidence, and final OOT are excluded. This
            policy-authorizing preview always uses the complete authorized
            development population; active descriptive filters are ignored.
          </p>
        </div>
        <div className="ml-auto flex gap-2">
          <span className="rounded-full border border-violet-200 bg-white px-2 py-1 text-[9px] font-semibold text-violet-900">
            NOT AN OUTCOME MODEL
          </span>
          <span className="rounded-full border border-amber-200 bg-amber-50 px-2 py-1 text-[9px] font-semibold text-amber-900">
            NOT AN ADOPTED IMPUTER
          </span>
          <button
            type="button"
            disabled={status === "loading"}
            onClick={run}
            className="rounded-lg bg-violet-800 px-3 py-2 text-xs font-semibold text-white disabled:opacity-50"
          >
            {status === "loading" ? "Running…" : "Run leakage-safe preview"}
          </button>
        </div>
      </div>
      {error ? (
        <div
          role="alert"
          className="mt-3 rounded-lg border border-rose-200 bg-rose-50 p-3 text-xs text-rose-900"
        >
          <b>Predicted preview failed:</b> {error}
        </div>
      ) : null}
      <div className="mt-3 grid gap-3 lg:grid-cols-2">
        <div className="rounded-xl border border-violet-100 bg-white p-3">
          <div className="text-[10px] font-semibold uppercase text-slate-500">
            Eligible predictor set
          </div>
          <p className="mt-2 break-words font-mono text-[10px] leading-5 text-slate-700">
            {detail.eligiblePredictors.join(" · ") ||
              "No eligible predictor contract returned."}
          </p>
        </div>
        <div className="rounded-xl border border-violet-100 bg-white p-3">
          <div className="text-[10px] font-semibold uppercase text-slate-500">
            Explicitly excluded
          </div>
          <div className="mt-2 space-y-1">
            {detail.excludedPredictorFields.map((item) => (
              <p key={item.field} className="text-[10px] text-slate-700">
                <b className="font-mono">{item.field}</b> · {item.reason}
              </p>
            ))}
            {!detail.excludedPredictorFields.length ? (
              <p className="text-[10px] text-slate-500">
                No exclusions reported.
              </p>
            ) : null}
          </div>
        </div>
      </div>
      {preview ? (
        <>
          <div className="mt-3 grid gap-2 sm:grid-cols-2 xl:grid-cols-6">
            <TreatmentMetric
              label="Missing rows imputed"
              value={formatInteger(preview.missingRowsImputed)}
              detail={`${formatPercent(preview.oofCoveragePercent)} OOF coverage`}
            />
            <TreatmentMetric
              label="Estimator"
              value={preview.estimator}
              detail={`Seed ${preview.seed}`}
            />
            <TreatmentMetric
              label="MAE / RMSE"
              value={`${formatValue(preview.mae)} / ${formatValue(preview.rmse)}`}
              detail="Observed-row chronological masking"
            />
            <TreatmentMetric
              label="Accuracy / log loss"
              value={`${formatValue(preview.accuracy)} / ${formatValue(preview.logLoss)}`}
              detail="Categorical preview where applicable"
            />
            <TreatmentMetric
              label="Domain violations"
              value={formatInteger(preview.domainBoundViolations)}
              detail="Must remain zero"
              tone={preview.domainBoundViolations ? "rose" : "emerald"}
            />
            <TreatmentMetric
              label="Runtime"
              value={`${formatValue(preview.runtimeSeconds, 2)} s`}
              detail={preview.artifactChecksum.slice(0, 14)}
            />
          </div>
          <p className="mt-3 break-all rounded-lg bg-white p-2 font-mono text-[10px] text-slate-500">
            Preview artifact: {preview.artifactChecksum}
          </p>
          <div className="mt-3 rounded-xl border border-violet-100 bg-white p-3">
            <h5 className="text-xs font-semibold text-slate-900">
              Out-of-fold predicted-value distribution
            </h5>
            <EChartsPanel
              option={predictedDistributionOption(preview)}
              height={260}
              ariaLabel={`Predicted imputation distribution ${preview.variable}`}
            />
          </div>
        </>
      ) : (
        <p className="mt-3 rounded-lg border border-dashed border-violet-300 bg-white p-4 text-center text-xs text-violet-900">
          Row-specific · preview not run. No single fabricated fill value is
          shown.
        </p>
      )}
    </section>
  );
}

function MissingEffectTable({ detail }: { detail: MissingDetail }) {
  return (
    <section className="rounded-2xl border border-slate-200 bg-white p-4">
      <h4 className="font-semibold text-slate-950">Imputation effect</h4>
      <div className="mt-3 grid gap-2 sm:grid-cols-2 xl:grid-cols-6">
        <TreatmentMetric
          label="Missing / observed"
          value={`${formatInteger(detail.effect.missingCount)} / ${formatInteger(detail.effect.observedCount)}`}
          detail="Physical development values"
        />
        <TreatmentMetric
          label="Filled"
          value={formatInteger(detail.effect.fillCount)}
          detail={`${formatInteger(detail.effect.retainedMissingCount)} retained missing`}
          tone={detail.effect.fillCount ? "cyan" : "slate"}
        />
        <TreatmentMetric
          label="Selected method"
          value={methodLabel(detail.method)}
          detail={
            detail.fillValue === null
              ? detail.fillPolicy
              : `Exact fill ${formatValue(detail.fillValue)}`
          }
        />
        <TreatmentMetric
          label="Mean before / after"
          value={`${formatValue(detail.effect.original.mean)} / ${formatValue(detail.effect.transformed.mean)}`}
          detail="Descriptive preview"
        />
        <TreatmentMetric
          label="Median before / after"
          value={`${formatValue(detail.effect.original.median)} / ${formatValue(detail.effect.transformed.median)}`}
          detail="Descriptive preview"
        />
        <TreatmentMetric
          label="Domain violations"
          value={formatInteger(detail.effect.domainViolations)}
          detail="Preview validation"
          tone={detail.effect.domainViolations ? "rose" : "emerald"}
        />
      </div>
      <div className="mt-3 grid gap-2 sm:grid-cols-3">
        <TreatmentMetric
          label="Std before / after"
          value={`${formatValue(detail.effect.original.std)} / ${formatValue(detail.effect.transformed.std)}`}
          detail="Descriptive preview"
        />
        <TreatmentMetric
          label="Affected games"
          value={formatInteger(detail.effect.affectedGames)}
          detail="Development-only"
        />
        <TreatmentMetric
          label="Affected batters / pitchers"
          value={`${formatInteger(detail.effect.affectedBatters)} / ${formatInteger(detail.effect.affectedPitchers)}`}
          detail="Unique affected entities"
        />
        <TreatmentMetric
          label="Paired indicator"
          value={detail.pairedIndicator ?? "Unavailable"}
          detail="Retained when authorized"
        />
        <TreatmentMetric
          label="Cold-start handling"
          value={detail.coldStartHandling}
          detail="Legitimate state; rows retained"
        />
        <TreatmentMetric
          label="Source failure handling"
          value={detail.sourceFailureHandling}
          detail="Separate from cold start"
        />
      </div>
      {detail.effect.originalCategories.length ||
      detail.effect.transformedCategories.length ? (
        <div className="mt-4 overflow-auto">
          <table className="w-full min-w-[640px] text-xs">
            <caption className="mb-2 text-left font-semibold text-slate-800">
              Category distribution before and after preview
            </caption>
            <thead>
              <tr className="text-left text-slate-500">
                <th className="border-b px-2 py-2">Category</th>
                <th className="border-b px-2 py-2">Before count</th>
                <th className="border-b px-2 py-2">Before %</th>
                <th className="border-b px-2 py-2">After count</th>
                <th className="border-b px-2 py-2">After %</th>
                <th className="border-b px-2 py-2">Imputed count</th>
              </tr>
            </thead>
            <tbody>
              {[
                ...new Set([
                  ...detail.effect.originalCategories.map((row) => row.value),
                  ...detail.effect.transformedCategories.map(
                    (row) => row.value,
                  ),
                ]),
              ].map((value) => {
                const before = detail.effect.originalCategories.find(
                  (row) => row.value === value,
                );
                const after = detail.effect.transformedCategories.find(
                  (row) => row.value === value,
                );
                return (
                  <tr key={value}>
                    <th
                      scope="row"
                      className="border-b px-2 py-2 text-left font-mono font-semibold"
                    >
                      {value}
                    </th>
                    <td className="border-b px-2 py-2">
                      {formatInteger(before?.count)}
                    </td>
                    <td className="border-b px-2 py-2">
                      {formatPercent(before?.percent)}
                    </td>
                    <td className="border-b px-2 py-2">
                      {formatInteger(after?.count)}
                    </td>
                    <td className="border-b px-2 py-2">
                      {formatPercent(after?.percent)}
                    </td>
                    <td className="border-b px-2 py-2">
                      {formatInteger(after?.imputedCount)}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      ) : null}
      <p className="mt-3 rounded-lg bg-slate-50 p-3 font-mono text-[11px] leading-5 text-slate-700">
        {detail.effect.formula}
        <br />
        {detail.effect.fittingRule}
      </p>
    </section>
  );
}

function MissingDetailDrawer({
  open,
  close,
  row,
  returnFocusRef,
  projectId,
  authority,
  filters,
  override,
  setOverride,
  applyToFamily,
  familyActionMessage,
  handoffFeatures,
}: {
  open: boolean;
  close: () => void;
  row: MissingTableRow | null;
  returnFocusRef: React.RefObject<HTMLElement>;
  projectId: string;
  authority: string;
  filters: ProjectEdaFilters;
  override: MissingOverride;
  setOverride: (override: MissingOverride) => void;
  applyToFamily: () => void;
  familyActionMessage: string | null;
  handoffFeatures: () => void;
}) {
  const governedPriorAuthority = useGovernedPriorAuthority(row?.variable);
  const request = useMemo(
    () =>
      row
        ? {
            variable: row.variable,
            filters: override.method === "PREDICTED" ? {} : filters,
            method: override.method,
            constantValue: override.constantValue,
            retainIndicator: override.retainIndicator,
            coldStartMethod: override.coldStartMethod,
            sourceFailureMethod: override.sourceFailureMethod,
            predictorSet: override.predictorSet,
            seed: override.seed,
            notes: override.notes,
          }
        : null,
    [filters, override, row],
  );
  const preview = useTreatmentPost<MissingDetail>(
    projectId,
    authority,
    "missing",
    "preview",
    request,
  );
  const predicted = useTreatmentMutation<PredictedPreview>(
    projectId,
    authority,
    "missing",
  );
  const previewDetail = preview.value?.data ?? null;
  const baseDetail =
    previewDetail?.variable === row?.variable ? previewDetail : null;
  const availablePredictors =
    baseDetail?.availablePredictors ?? baseDetail?.eligiblePredictors ?? [];
  const selectedPredictors =
    override.predictorSet === undefined
      ? (baseDetail?.eligiblePredictors ?? [])
      : override.predictorSet;
  const predictorSelectionLimit = 12;
  const canonicalPredictedPreviewSeed =
    baseDetail?.canonicalPredictedPreviewSeed ?? PREDICTED_PREVIEW_SEED;
  const predictedPreviewRequestSpec =
    row && override.method === "PREDICTED" && selectedPredictors.length
      ? {
          variable: row.variable,
          filters: {},
          method: "PREDICTED",
          predictorSet: selectedPredictors,
          seed: canonicalPredictedPreviewSeed,
          design: PREDICTED_PREVIEW_DESIGN,
        }
      : null;
  const currentPredictedRequestIdentity = predictedPreviewRequestSpec
    ? canonicalPolicySignature(predictedPreviewRequestSpec)
    : null;
  const currentPredictedRequestIdentityRef = useRef<string | null>(null);
  currentPredictedRequestIdentityRef.current = currentPredictedRequestIdentity;
  const completedPredictedRequestIdentity = useRef<string | null>(null);
  useEffect(() => {
    if (
      completedPredictedRequestIdentity.current !== null &&
      completedPredictedRequestIdentity.current !==
        currentPredictedRequestIdentity
    ) {
      completedPredictedRequestIdentity.current = null;
      predicted.reset();
    }
  }, [currentPredictedRequestIdentity, predicted.reset]);
  const mutationPredictedResult =
    row &&
    completedPredictedRequestIdentity.current ===
      currentPredictedRequestIdentity &&
    predictedPreviewMatchesRequest(
      predicted.value?.data,
      row.variable,
      selectedPredictors,
      canonicalPredictedPreviewSeed,
    )
      ? predicted.value.data
      : null;
  const storedPredictedResult =
    row &&
    predictedPreviewMatchesRequest(
      baseDetail?.predictedPreview,
      row.variable,
      selectedPredictors,
      canonicalPredictedPreviewSeed,
    )
      ? baseDetail.predictedPreview
      : null;
  const predictedResult = mutationPredictedResult ?? storedPredictedResult;
  const detail =
    baseDetail && override.method === "PREDICTED" && predictedResult?.after
      ? {
          ...baseDetail,
          fillPolicy: "Row-specific · OOF preview available",
          before: predictedResult.observedDistribution,
          after: predictedResult.after,
          sharedAxis: predictedResult.sharedAxis,
          imputedDistribution: predictedResult.imputedDistribution,
          effect: {
            ...baseDetail.effect,
            missingCount: predictedResult.aggregateEffect.originalMissingCount,
            observedCount: predictedResult.aggregateEffect.observedCount,
            fillCount: predictedResult.aggregateEffect.imputedCount,
            retainedMissingCount:
              predictedResult.aggregateEffect.previewUnfilledMissingCount,
            domainViolations: predictedResult.domainBoundViolations,
            original: predictedResult.aggregateEffect.original,
            transformed: predictedResult.aggregateEffect.combined,
            originalCategories:
              predictedResult.observedDistribution.categories ?? [],
            transformedCategories: predictedResult.after.categories ?? [],
            formula: predictedResult.aggregateEffect.semantics,
          },
        }
      : baseDetail;
  const constantInvalid =
    override.method === "CONSTANT" &&
    (override.constantValue === null ||
      override.constantValue === undefined ||
      override.constantValue === "");
  return (
    <CockpitDrawer
      open={open}
      onClose={close}
      returnFocusRef={returnFocusRef}
      title={
        row
          ? `Missing-value analysis · ${row.variable}`
          : "Missing-value analysis"
      }
      eyebrow="Development-only descriptive preview"
      description="Observed and imputed values remain visually distinct. Final treatment parameters are fitted inside each chronological training fold."
      widthClassName="max-w-none"
      testId="stage3-missing-detail"
    >
      <div className="space-y-4 p-4 sm:p-6">
        <section className="grid gap-3 rounded-2xl border border-slate-200 bg-white p-4 lg:grid-cols-4">
          <label className="text-[10px] font-semibold uppercase text-slate-500">
            Imputation method
            <select
              value={override.method}
              onChange={(event) =>
                setOverride({
                  ...override,
                  method: event.target.value as ImputationMethod,
                })
              }
              className="mt-1 block w-full rounded-lg border border-slate-300 px-2 py-2 text-xs font-normal normal-case"
            >
              {METHODS.map((item) => (
                <option
                  key={item.value}
                  value={item.value}
                  disabled={
                    row ? !row.eligibleMethods.includes(item.value) : false
                  }
                  title={
                    row?.ineligibleMethodReasons?.[item.value] ?? item.detail
                  }
                >
                  {item.label}
                </option>
              ))}
            </select>
          </label>
          {row && Object.keys(row.ineligibleMethodReasons ?? {}).length ? (
            <div
              className="rounded-lg border border-amber-200 bg-amber-50 p-2 text-[10px] leading-4 text-amber-950"
              aria-label="Unavailable imputation method explanations"
            >
              <b>Unavailable methods:</b>
              <ul className="mt-1 list-disc pl-4">
                {Object.entries(row.ineligibleMethodReasons ?? {}).map(
                  ([method, reason]) => (
                    <li key={method}>
                      <span className="font-semibold">
                        {methodLabel(method)}
                      </span>{" "}
                      — {reason}
                    </li>
                  ),
                )}
              </ul>
            </div>
          ) : null}
          <label className="text-[10px] font-semibold uppercase text-slate-500">
            Constant value
            <input
              value={override.constantValue ?? ""}
              disabled={override.method !== "CONSTANT"}
              onChange={(event) =>
                setOverride({ ...override, constantValue: event.target.value })
              }
              aria-invalid={constantInvalid}
              className="mt-1 block w-full rounded-lg border border-slate-300 px-2 py-2 text-xs font-normal disabled:bg-slate-100"
            />
          </label>
          <label className="text-[10px] font-semibold uppercase text-slate-500">
            Cold-start rule
            <select
              value={override.coldStartMethod ?? "RETAIN_WITH_INDICATOR"}
              onChange={(event) =>
                setOverride({
                  ...override,
                  coldStartMethod: event.target.value,
                })
              }
              className="mt-1 block w-full rounded-lg border border-slate-300 px-2 py-2 text-xs font-normal normal-case"
            >
              <option
                value="GOVERNED_PRIOR_WITH_INDICATOR"
                disabled={detail?.governedPriorAvailable !== true}
              >
                Fold-local governed prior + indicator
              </option>
              <option value="RETAIN_WITH_INDICATOR">
                Retain missing + indicator
              </option>
              <option value="REVIEW_REQUIRED">Review required</option>
            </select>
          </label>
          <div
            role="status"
            className={`rounded-lg border p-2 text-[10px] leading-4 ${
              detail?.governedPriorAvailable
                ? "border-emerald-200 bg-emerald-50 text-emerald-950"
                : "border-amber-200 bg-amber-50 text-amber-950"
            }`}
          >
            {detail?.governedPriorAvailable
              ? "A registered point-in-time governed-prior authority is available for this variable. It will still be fitted inside each training fold."
              : detail?.governedPriorUnavailableReason ||
                "Governed prior unavailable: no registered hierarchical or league-prior authority exists for this variable. Retain missing with its indicator, or require review."}
          </div>
          {row && governedPriorAuthority ? (
            <div className="lg:col-span-4">
              <GovernedPriorAuthorityCard
                featureName={row.variable}
                authority={governedPriorAuthority}
              />
            </div>
          ) : null}
          <label className="text-[10px] font-semibold uppercase text-slate-500">
            Source/computation failure
            <select
              value={override.sourceFailureMethod ?? "REVIEW_REQUIRED"}
              onChange={(event) =>
                setOverride({
                  ...override,
                  sourceFailureMethod: event.target.value,
                })
              }
              className="mt-1 block w-full rounded-lg border border-slate-300 px-2 py-2 text-xs font-normal normal-case"
            >
              <option value="REVIEW_REQUIRED">Review required</option>
              <option value="RETAIN_WITH_INDICATOR">
                Retain missing + source-failure indicator
              </option>
              <option value="DROP_VARIABLE">Drop variable</option>
            </select>
          </label>
          <label className="flex items-center gap-2 text-xs font-semibold text-slate-700">
            <input
              type="checkbox"
              checked={override.retainIndicator ?? true}
              onChange={(event) =>
                setOverride({
                  ...override,
                  retainIndicator: event.target.checked,
                })
              }
            />
            Retain paired missingness indicator
          </label>
          <label className="lg:col-span-2 text-[10px] font-semibold uppercase text-slate-500">
            Variable notes
            <input
              value={override.notes ?? ""}
              onChange={(event) =>
                setOverride({ ...override, notes: event.target.value })
              }
              className="mt-1 block w-full rounded-lg border border-slate-300 px-3 py-2 text-xs font-normal normal-case"
            />
          </label>
          <button
            type="button"
            onClick={applyToFamily}
            className="inline-flex items-center justify-center gap-1 rounded-lg border border-slate-300 bg-white px-3 py-2 text-xs font-semibold text-slate-700"
          >
            <Copy size={12} />
            Apply to feature family
          </button>
          <button
            type="button"
            onClick={handoffFeatures}
            className="rounded-lg border border-cyan-200 bg-cyan-50 px-3 py-2 text-xs font-semibold text-cyan-900"
          >
            Bookmark indicator for Feature Engineering
          </button>
        </section>
        {familyActionMessage ? (
          <div
            role="status"
            className="rounded-lg border border-cyan-200 bg-cyan-50 p-3 text-xs text-cyan-950"
          >
            {familyActionMessage}
          </div>
        ) : null}
        {constantInvalid ? (
          <p className="rounded-lg border border-rose-200 bg-rose-50 p-3 text-xs text-rose-900">
            A constant treatment requires an explicit value valid for this
            variable’s data type and governed domain.
          </p>
        ) : null}
        {override.method === "EXCLUDE_ROW" ? (
          <div className="rounded-xl border border-rose-300 bg-rose-50 p-4 text-xs leading-5 text-rose-950">
            <AlertTriangle size={15} className="mr-1 inline" />
            <b>High-risk row exclusion:</b> inspect exact population loss and
            entity/target concentrations. Missingness alone is not an automatic
            deletion rule.
          </div>
        ) : null}
        <StudioRequestState
          status={preview.status}
          error={preview.error}
          retry={preview.retry}
        />
        {detail ? (
          <>
            <div className="flex flex-wrap items-center gap-2 rounded-xl border border-cyan-200 bg-cyan-50 p-3 text-xs text-cyan-950">
              <Layers3 size={14} />
              <b>{detail.fillPolicy}</b>
              <span className="ml-auto font-semibold">
                DESCRIPTIVE PREVIEW VALUES · FINAL VALUES ARE FIT INSIDE EACH
                CHRONOLOGICAL TRAINING FOLD
              </span>
            </div>
            {override.method === "PREDICTED" ? (
              <fieldset
                className="rounded-2xl border border-violet-200 bg-violet-50/40 p-4"
                data-testid="stage3-missing-predictor-set-editor"
              >
                <legend className="px-1 text-xs font-semibold uppercase tracking-wide text-violet-900">
                  Cutoff-safe predictor set
                </legend>
                <div className="flex flex-wrap items-center gap-2">
                  <button
                    type="button"
                    onClick={() =>
                      setOverride({
                        ...override,
                        predictorSet: availablePredictors.slice(
                          0,
                          predictorSelectionLimit,
                        ),
                      })
                    }
                    className="rounded-lg border border-violet-300 bg-white px-2 py-1 text-[10px] font-semibold text-violet-900"
                  >
                    Use all eligible
                  </button>
                  <button
                    type="button"
                    onClick={() =>
                      setOverride({ ...override, predictorSet: undefined })
                    }
                    className="rounded-lg border border-violet-300 bg-white px-2 py-1 text-[10px] font-semibold text-violet-900"
                  >
                    Restore governed default
                  </button>
                  <span className="ml-auto text-[10px] text-slate-600">
                    {selectedPredictors.length} selected of{" "}
                    {availablePredictors.length}
                    available (maximum {predictorSelectionLimit}). Target,
                    same-game future evidence, identifiers, and final OOT remain
                    excluded.
                  </span>
                </div>
                <div className="mt-3 grid max-h-48 gap-2 overflow-auto rounded-lg border border-violet-100 bg-white p-3 sm:grid-cols-2 xl:grid-cols-3">
                  {availablePredictors.map((predictor) => {
                    const selected = selectedPredictors.includes(predictor);
                    return (
                      <label
                        key={predictor}
                        className="flex items-center gap-2 text-[10px] text-slate-700"
                      >
                        <input
                          type="checkbox"
                          checked={selected}
                          disabled={
                            (selected && selectedPredictors.length <= 1) ||
                            (!selected &&
                              selectedPredictors.length >=
                                predictorSelectionLimit)
                          }
                          onChange={() => {
                            const next = selected
                              ? selectedPredictors.filter(
                                  (item) => item !== predictor,
                                )
                              : [...selectedPredictors, predictor];
                            setOverride({ ...override, predictorSet: next });
                          }}
                        />
                        <span className="font-mono">{predictor}</span>
                      </label>
                    );
                  })}
                </div>
              </fieldset>
            ) : null}
            <div className="grid gap-4 xl:grid-cols-2">
              <section className="rounded-2xl border border-slate-200 bg-white p-4">
                <h4 className="font-semibold text-slate-950">
                  Before imputation
                </h4>
                <p className="mt-1 text-xs text-slate-500">
                  {formatInteger(detail.before.observedCount)} observed ·{" "}
                  {formatInteger(detail.before.missingCount)} physically missing
                </p>
                <EChartsPanel
                  option={missingDistributionOption(detail, false)}
                  height={340}
                  ariaLabel={`Before missing-value treatment ${row?.variable}`}
                />
              </section>
              <section className="rounded-2xl border border-emerald-200 bg-white p-4">
                <h4 className="font-semibold text-slate-950">
                  After imputation preview
                </h4>
                <p className="mt-1 text-xs text-slate-500">
                  {detail.method === "RETAIN_WITH_INDICATOR"
                    ? "Distribution unchanged; missing values and indicator remain explicit."
                    : detail.method === "PREDICTED" && !predictedResult
                      ? "Row-specific · preview required. No fabricated global fill value."
                      : "Imputed observations use the amber patterned overlay; Gold remains unchanged."}
                </p>
                <EChartsPanel
                  option={missingDistributionOption(detail, true)}
                  height={340}
                  ariaLabel={`After missing-value treatment ${row?.variable}`}
                />
              </section>
            </div>
            {override.method === "PREDICTED" ? (
              <PredictedPreviewPanel
                detail={detail}
                preview={predictedResult}
                status={predicted.status}
                error={predicted.error}
                run={() => {
                  if (!row || !predictedPreviewRequestSpec) return;
                  const requestIdentity = canonicalPolicySignature(
                    predictedPreviewRequestSpec,
                  );
                  completedPredictedRequestIdentity.current = requestIdentity;
                  void predicted
                    .run("predicted-preview", predictedPreviewRequestSpec)
                    .then((value) => {
                      if (
                        !value ||
                        currentPredictedRequestIdentityRef.current !==
                          requestIdentity ||
                        !predictedPreviewMatchesRequest(
                          value.data,
                          row.variable,
                          predictedPreviewRequestSpec.predictorSet,
                          predictedPreviewRequestSpec.seed,
                        )
                      )
                        return;
                      setOverride({
                        ...override,
                        predictorSet: value.data.eligiblePredictors,
                        seed: value.data.seed,
                      });
                    });
                }}
              />
            ) : null}
            <MissingEffectTable detail={detail} />
          </>
        ) : null}
      </div>
    </CockpitDrawer>
  );
}

export function ProjectBoundMissingStudio({
  state,
  projectId,
  go,
}: {
  state: CurrentGoldReviewState;
  projectId: string;
  go: (id: string) => void;
}) {
  const { notes, setNote } = useCockpitStore();
  const authority = authorityKey(state);
  const review = state.review;
  const handoff = useMemo(
    () =>
      parseHandoff(
        notes["stage3.eda.handoff"],
        notes["stage3.treatment.pendingMissing"],
        authority,
      ),
    [authority, notes],
  );
  const [filterState, setFilterState] = useState<StudioFilterState>({
    filters: handoff.filters,
    search: "",
    family: "",
    coreScope: "",
    dataType: "",
    severity: "",
    includeAdvanced: false,
  });
  const [globalMethod, setGlobalMethod] = useState("DATA_TYPE_AWARE");
  const [overrides, setOverrides] = useState<Record<string, MissingOverride>>(
    {},
  );
  const [selected, setSelected] = useState<string[]>(handoff.selectedVariables);
  const [activeRow, setActiveRow] = useState<MissingTableRow | null>(null);
  const [sort, setSort] = useState({
    field: "numberOfMissingValues",
    direction: "desc" as "asc" | "desc",
  });
  const [page, setPage] = useState(1);
  const [notesValue, setNotesValue] = useState("");
  const [refreshKey, setRefreshKey] = useState(0);
  const [bulkStatus, setBulkStatus] = useState<"idle" | "loading" | "error">(
    "idle",
  );
  const [bulkError, setBulkError] = useState<string | null>(null);
  const [bulkNotice, setBulkNotice] = useState<string | null>(null);
  const detailTrigger = useRef<HTMLElement | null>(null);
  const hydratedPolicyIdentity = useRef<string | null>(null);
  const enabled = state.status === "ready" && Boolean(review);
  const metadata = useProjectEdaMetadata(projectId, authority, enabled);
  const summary = useTreatmentGet<MissingSummary>(
    projectId,
    authority,
    "missing",
    "summary",
    enabled,
    refreshKey,
  );
  const policyQuery = useTreatmentGet<TreatmentPolicy<MissingOverride>>(
    projectId,
    authority,
    "missing",
    "policy",
    enabled,
    refreshKey,
  );
  const policy = policyQuery.value?.data ?? summary.value?.data.policy ?? null;
  useEffect(() => {
    if (!policy) return;
    const policyIdentity = `${authority}:${policy.policyId ?? "none"}:${policy.checksum ?? "none"}`;
    if (hydratedPolicyIdentity.current === policyIdentity) return;
    hydratedPolicyIdentity.current = policyIdentity;
    setGlobalMethod(policy.globalMethod || "DATA_TYPE_AWARE");
    setOverrides(
      sanitizeColdStartOverrides(
        policy.overrides ?? {},
        policy.governedPriorEligibleVariables ?? [],
      ),
    );
    setNotesValue(policy.notes ?? "");
  }, [authority, policy]);
  const tableRequest = useMemo(
    () =>
      enabled
        ? {
            authorityKey: authority,
            filters: filterState.filters,
            search: filterState.search,
            families: filterState.family ? [filterState.family] : [],
            coreScope: filterState.coreScope,
            dataTypes: filterState.dataType ? [filterState.dataType] : [],
            severity: filterState.severity,
            includeAdvanced: filterState.includeAdvanced,
            sort,
            page,
            pageSize: PAGE_SIZE,
            globalMethod,
            overrides,
            policyVersion: policy?.policyVersion ?? null,
          }
        : null,
    [
      authority,
      enabled,
      filterState,
      globalMethod,
      overrides,
      page,
      policy?.policyVersion,
      sort,
    ],
  );
  const table = useTreatmentPost<PaginatedTreatmentTable<MissingTableRow>>(
    projectId,
    authority,
    "missing",
    "table",
    tableRequest,
  );
  const saveMutation = useTreatmentMutation<{
    policy: TreatmentPolicy<MissingOverride>;
  }>(projectId, authority, "missing");
  const adoptMutation = useTreatmentMutation<{
    policy: TreatmentPolicy<MissingOverride>;
  }>(projectId, authority, "missing");
  if (state.status === "loading" || state.status === "idle")
    return (
      <StudioRequestState
        status="loading"
        error={null}
        retry={() => undefined}
      />
    );
  if (state.status === "error" || !review)
    return (
      <StudioRequestState
        status="error"
        error={state.error || "Project-bound Stage 3 authority is unavailable."}
        retry={() => undefined}
      />
    );
  const rows = table.value?.data.rows ?? [];
  const summaryData = summary.value?.data ?? null;
  const effectiveOverride = activeRow
    ? (overrides[activeRow.variable] ?? {
        ...DEFAULT_OVERRIDE,
        method: activeRow.selectedImputationMethod ?? "RETAIN_WITH_INDICATOR",
      })
    : DEFAULT_OVERRIDE;
  const setOverride = (variable: string, next: MissingOverride) =>
    setOverrides((current) => ({ ...current, [variable]: next }));
  const policyBody = {
    policyId: policy?.policyId ?? undefined,
    projectId,
    goldManifestSha: review.goldAuthority.manifestSha,
    developmentCutoff: review.matrix.development.endDate,
    finalOotIdentity: `${review.matrix.finalOot.startDate}:${review.matrix.finalOot.endDate}:${review.matrix.finalOot.rows}`,
    globalMethod,
    overrides,
    notes: notesValue,
    fittingRule: "FIT_IMPUTATION_INSIDE_EACH_CHRONOLOGICAL_TRAINING_FOLD",
    coldStartDefault: "RETAIN_WITH_INDICATOR",
    sourceFailureDefault: "REVIEW_REQUIRED",
  };
  const draftHasUnsavedChanges =
    policy?.status === "DRAFT" &&
    missingPolicyControlSignature(globalMethod, overrides, notesValue) !==
      missingPolicyControlSignature(
        policy.globalMethod,
        policy.overrides,
        policy.notes,
      );
  const refreshPolicy = () => {
    setRefreshKey((value) => value + 1);
  };
  const reset = () => {
    setGlobalMethod("DATA_TYPE_AWARE");
    setOverrides({});
    setSelected(handoff.pendingVariables);
    setNotesValue("");
    setPage(1);
  };
  const toggleSort = (field: string) =>
    setSort((current) =>
      current.field === field
        ? { field, direction: current.direction === "desc" ? "asc" : "desc" }
        : { field, direction: "desc" },
    );
  const loadAllRows = async (request: Record<string, unknown>) => {
    setBulkStatus("loading");
    setBulkError(null);
    setBulkNotice(null);
    try {
      const result = await fetchAllTreatmentRows<MissingTableRow>(
        projectId,
        authority,
        "missing",
        request,
      );
      setBulkStatus("idle");
      return result;
    } catch (error) {
      setBulkStatus("error");
      setBulkError(
        error instanceof Error
          ? error.message
          : "Full filtered table request failed.",
      );
      return null;
    }
  };
  const title =
    summary.status !== "ready"
      ? "Analysis not yet run"
      : summaryData?.status === "NO_MISSING_VALUES"
        ? "No physical missingness in eligible predictors"
        : summaryData?.status === "ANALYZED"
          ? "Physical missingness, cold start, and failures remain separate"
          : "No treatment adopted";
  const compare = (
    <div className="grid gap-3 sm:grid-cols-2">
      <TreatmentMetric
        label="Current proposal"
        value={globalMethod.replaceAll("_", " ")}
        detail={`${Object.keys(overrides).length} per-variable overrides`}
        tone="cyan"
      />
      <TreatmentMetric
        label="Saved policy"
        value={policy?.globalMethod.replaceAll("_", " ") ?? "Unavailable"}
        detail={
          policy
            ? `Version ${policy.policyVersion ?? "draft"} · ${Object.keys(policy.overrides).length} overrides`
            : "No saved policy"
        }
      />
    </div>
  );
  return (
    <TreatmentStudioShell
      kind="missing"
      projectId={projectId}
      authorityKey={authority}
      review={review}
      title="Project-bound Missing-Value Treatment Studio"
      description="Separate physical missingness, legitimate cold start, insufficient history, and source/computation failure before versioning fold-local imputation rules."
      policy={policy}
    >
      {handoff.pendingVariables.length ? (
        <section
          className="rounded-xl border border-amber-300 bg-amber-50 p-3 text-xs leading-5 text-amber-950"
          data-testid="stage3-pending-missing-requirement"
        >
          <b>Pending requirements from Outliers:</b> These variables were
          previewed as SET OUTLIERS TO MISSING. No imputation is active until a
          policy is explicitly saved or adopted.
          <ul className="mt-2 list-disc pl-5 font-mono">
            {handoff.pendingVariables.map((variable) => (
              <li key={variable}>{variable}</li>
            ))}
          </ul>
        </section>
      ) : null}
      <TreatmentDecisionHeader
        kind="missing"
        status={summary.status}
        summary={title}
      >
        <div className="grid gap-2 sm:grid-cols-2 xl:grid-cols-6">
          <TreatmentMetric
            label="Active proposal"
            value={methodLabel(
              table.value?.data.activeGlobalMethod ?? globalMethod,
            )}
            detail={`${formatInteger(summaryData?.eligiblePredictors)} eligible predictors · fold-local fitting required`}
            tone="cyan"
          />
          <TreatmentMetric
            label="Physical gaps"
            value={formatInteger(summaryData?.predictorsWithPhysicalMissing)}
            detail={`${formatInteger(summaryData?.rowsWithPhysicalMissing)} affected rows`}
            tone="amber"
          />
          <TreatmentMetric
            label="Macro cell missingness"
            value={formatPercent(summaryData?.macroPredictorCellMissingPercent)}
            detail={`${summaryData?.largestMissingVariable ?? "—"} · ${formatPercent(summaryData?.largestMissingPercent)}`}
          />
          <TreatmentMetric
            label="Cold-start rows"
            value={formatInteger(summaryData?.coldStartRows)}
            detail="Legitimate state; rows retained"
            tone="cyan"
          />
          <TreatmentMetric
            label="Source / computation failure"
            value={`${formatInteger(summaryData?.sourceUnavailableRows)} / ${formatInteger(summaryData?.computationFailureRows)}`}
            detail="Kept separate from cold start"
            tone="amber"
          />
          <TreatmentMetric
            label="Indicators / policy"
            value={`${formatInteger(summaryData?.missingnessIndicatorCount)} · ${policy?.status ?? "NOT ADOPTED"}`}
            detail={`Policy version ${policy?.policyVersion ?? "—"} · OOT LOCKED`}
            tone={policy?.status === "ADOPTED" ? "emerald" : "slate"}
          />
        </div>
      </TreatmentDecisionHeader>
      <TreatmentStudioFilters
        state={filterState}
        setState={(next) => {
          setFilterState(next);
          setPage(1);
        }}
        families={metadata.value?.data.families.map((item) => item.name) ?? []}
        dataTypes={[
          ...new Set(
            metadata.value?.data.variables.map((item) => item.dataType) ?? [],
          ),
        ]}
        severities={[
          { value: "PHYSICAL_MISSING", label: "Has physical missing values" },
          { value: "COLD_START", label: "Cold start / no prior history" },
          {
            value: "SOURCE_FAILURE",
            label: "Source unavailable / computation failure",
          },
          { value: "COMPLETE", label: "Physically complete" },
        ]}
        seasons={metadata.value?.data.filterOptions.seasons ?? []}
        months={metadata.value?.data.filterOptions.months ?? []}
      />
      {handoff.outcomeFilterRemoved ? (
        <div
          role="status"
          className="rounded-xl border border-amber-300 bg-amber-50 p-3 text-xs leading-5 text-amber-950"
          data-testid="stage3-treatment-outcome-filter-removed"
        >
          <b>Outcome-class filter removed.</b> Missing-value fill previews
          cannot be conditioned on the target outcome. All other authorized
          development-only handoff filters were preserved.
        </div>
      ) : null}
      <section
        className="rounded-2xl border border-slate-200 bg-white p-4 shadow-sm"
        data-testid="stage3-missing-global-policy"
      >
        <div className="flex flex-wrap items-end gap-3">
          <label className="min-w-64 text-[10px] font-semibold uppercase text-slate-500">
            Global data-type-aware proposal
            <select
              aria-label="Global imputation policy"
              value={globalMethod}
              onChange={(event) => {
                setGlobalMethod(event.target.value);
                setPage(1);
              }}
              className="mt-1 block w-full rounded-lg border border-slate-300 px-3 py-2 text-xs font-normal normal-case"
            >
              <option value="DATA_TYPE_AWARE">
                Governed prior when bound · otherwise median / mode
              </option>
              <option value="MEDIAN">Median where eligible</option>
              <option value="MODE">Mode where eligible</option>
              <option value="RETAIN_WITH_INDICATOR">
                Retain missing + indicator where eligible
              </option>
            </select>
          </label>
          <button
            type="button"
            onClick={() => setOverrides({})}
            className="rounded-lg border border-slate-300 px-3 py-2 text-xs font-semibold text-slate-700"
          >
            Apply global to all eligible
          </button>
          <button
            type="button"
            disabled={
              !selected.length || !tableRequest || bulkStatus === "loading"
            }
            onClick={() => {
              if (!tableRequest) return;
              void loadAllRows({
                ...tableRequest,
                filters: {},
                search: "",
                families: [],
                coreScope: "",
                dataTypes: [],
                severity: "",
                includeAdvanced: false,
                globalMethod: "DATA_TYPE_AWARE",
                overrides: {},
              }).then((allRows) => {
                if (!allRows) return;
                const selectedRows = allRows.filter(
                  (row) =>
                    row.eligible &&
                    selected.includes(row.variable) &&
                    row.selectedImputationMethod !== null &&
                    row.eligibleMethods.includes(row.selectedImputationMethod),
                );
                const skipped = selected.length - selectedRows.length;
                setOverrides((current) => ({
                  ...current,
                  ...Object.fromEntries(
                    selectedRows.map((row) => [
                      row.variable,
                      {
                        ...DEFAULT_OVERRIDE,
                        method:
                          row.selectedImputationMethod ??
                          "RETAIN_WITH_INDICATOR",
                      },
                    ]),
                  ),
                }));
                setBulkNotice(
                  skipped
                    ? `Applied each variable’s valid data-type-aware default to ${selectedRows.length} selected variables; skipped ${skipped} unavailable or ineligible selections.`
                    : `Applied each variable’s valid data-type-aware default to all ${selectedRows.length} selected variables.`,
                );
              });
            }}
            className="rounded-lg border border-slate-300 px-3 py-2 text-xs font-semibold text-slate-700 disabled:opacity-40"
          >
            Apply proposal to selected
          </button>
          <button
            type="button"
            disabled={!selected.length}
            onClick={() =>
              setOverrides((current) =>
                Object.fromEntries(
                  Object.entries(current).filter(
                    ([variable]) => !selected.includes(variable),
                  ),
                ),
              )
            }
            className="rounded-lg border border-slate-300 px-3 py-2 text-xs font-semibold text-slate-700 disabled:opacity-40"
          >
            Clear selected overrides
          </button>
          <span className="ml-auto max-w-lg text-[10px] leading-4 text-slate-500">
            Exact executable prior authority takes precedence for bound player-state
            features; other continuous missingness → median; other binary/categorical
            missingness → mode; source/computation failure → review required; simulator
            state → supplied by simulator.
          </span>
        </div>
        {bulkNotice ? (
          <div
            role="status"
            className="mt-3 rounded-lg border border-cyan-200 bg-cyan-50 p-3 text-xs text-cyan-950"
          >
            {bulkNotice}
          </div>
        ) : null}
      </section>
      <section
        className="rounded-2xl border border-slate-200 bg-white shadow-sm"
        data-testid="stage3-missing-summary-table"
      >
        <div className="flex flex-wrap items-center gap-2 border-b border-slate-100 p-4">
          <div>
            <h3 className="font-semibold text-slate-950">
              Eligible predictor missing-value table
            </h3>
            <p className="mt-1 text-xs text-slate-500">
              Default order: highest physical missing count first. Cold-start
              and failure reasons remain reconciled separately. Advanced
              inspection appends read-only excluded metadata rows with no
              fabricated missingness values.
            </p>
          </div>
          <span className="ml-auto text-xs text-slate-500">
            {formatInteger(table.value?.data.totalRows)} predictors ·{" "}
            {formatInteger(table.value?.data.excludedMetadataRows)} read-only
          </span>
          <DownloadAggregatedButton
            disabled={!tableRequest || bulkStatus === "loading"}
            onClick={() => {
              if (!tableRequest) return;
              void loadAllRows(tableRequest).then((allRows) => {
                if (allRows)
                  downloadAggregatedCsv(
                    "project-bound-missing-table.csv",
                    allRows as unknown as Record<string, unknown>[],
                  );
              });
            }}
          />
        </div>
        {bulkError ? (
          <div
            role="alert"
            className="m-3 rounded-lg border border-rose-200 bg-rose-50 p-3 text-xs text-rose-900"
          >
            Full-table action failed: {bulkError}
          </div>
        ) : null}
        <StudioRequestState
          status={table.status}
          error={table.error}
          retry={table.retry}
        />
        {table.status === "ready" ? (
          <div className="overflow-auto">
            <table className="min-w-[2850px] text-[11px]">
              <thead className="sticky top-0 z-20 bg-slate-100 text-left text-[9px] uppercase tracking-wide text-slate-500">
                <tr>
                  {MISSING_COLUMNS.map(({ label, field }, index) => (
                    <th
                      key={label}
                      className={`border-b px-3 py-2 ${index < 2 ? "xl:sticky xl:z-30 xl:bg-slate-100" : ""}`}
                      style={
                        index === 0
                          ? { left: 0 }
                          : index === 1
                            ? { left: 165 }
                            : undefined
                      }
                    >
                      {field ? (
                        <button
                          type="button"
                          onClick={() => toggleSort(field)}
                          className="inline-flex items-center gap-1 text-left"
                        >
                          {label}
                          {sort.field === field ? (
                            sort.direction === "desc" ? (
                              <ArrowDown size={10} />
                            ) : (
                              <ArrowUp size={10} />
                            )
                          ) : null}
                        </button>
                      ) : (
                        label
                      )}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {rows.map((row) => {
                  const override = overrides[row.variable];
                  const eligible = row.eligible !== false;
                  return (
                    <tr
                      key={row.variable}
                      className={
                        eligible
                          ? "hover:bg-cyan-50/40"
                          : "bg-slate-50 text-slate-500"
                      }
                    >
                      <td className="w-[165px] border-b bg-white px-3 py-2 xl:sticky xl:left-0 xl:z-10">
                        <label className="flex items-center gap-2">
                          <input
                            type="checkbox"
                            disabled={!eligible}
                            checked={selected.includes(row.variable)}
                            onChange={() => {
                              if (!eligible) return;
                              setSelected((current) =>
                                current.includes(row.variable)
                                  ? current.filter(
                                      (item) => item !== row.variable,
                                    )
                                  : [...current, row.variable],
                              );
                            }}
                          />
                          <b className="tabular-nums">
                            {formatInteger(row.numberOfMissingValues)}
                          </b>
                        </label>
                      </td>
                      <td className="w-[230px] border-b bg-white px-3 py-2 font-mono font-semibold text-slate-900 xl:sticky xl:left-[165px] xl:z-10">
                        {row.variable}
                        {override || row.override ? (
                          <span className="ml-2 rounded bg-cyan-100 px-1.5 py-0.5 font-sans text-[8px] text-cyan-800">
                            OVERRIDE
                          </span>
                        ) : null}
                      </td>
                      <td className="border-b px-3 py-2">
                        {formatPercent(row.missingPercent)}
                      </td>
                      <td className="border-b px-3 py-2">
                        {formatInteger(row.developmentN)}
                      </td>
                      <td className="border-b px-3 py-2">
                        {formatInteger(row.observedN)}
                      </td>
                      <td className="border-b px-3 py-2">{row.dataType}</td>
                      <td className="border-b px-3 py-2">
                        {row.featureFamily}
                      </td>
                      <td className="border-b px-3 py-2">
                        <span
                          className={
                            /NO_PRIOR|INSUFFICIENT/i.test(row.primaryReason)
                              ? "rounded bg-cyan-50 px-2 py-1 text-cyan-900"
                              : /FAILURE|UNAVAILABLE/i.test(row.primaryReason)
                                ? "rounded bg-amber-50 px-2 py-1 text-amber-900"
                                : ""
                          }
                        >
                          {row.primaryReason}
                        </span>
                      </td>
                      <td className="border-b px-3 py-2">
                        {formatInteger(row.noPriorHistoryCount)}
                      </td>
                      <td className="border-b px-3 py-2">
                        {formatInteger(row.insufficientHistoryCount)}
                      </td>
                      <td className="border-b px-3 py-2">
                        {formatInteger(row.sourceUnavailableCount)}
                      </td>
                      <td className="border-b px-3 py-2">
                        {formatInteger(row.computationFailureCount)}
                      </td>
                      <td className="border-b px-3 py-2 font-mono">
                        {row.pairedMissingnessIndicator ?? "—"}
                      </td>
                      <td className="border-b bg-white px-3 py-2 xl:sticky xl:right-[390px] xl:z-10">
                        {eligible ? (
                          <select
                            aria-label={`Imputation method for ${row.variable}`}
                            value={
                              override?.method ??
                              row.selectedImputationMethod ??
                              "RETAIN_WITH_INDICATOR"
                            }
                            onChange={(event) =>
                              setOverride(row.variable, {
                                ...(override ?? { ...DEFAULT_OVERRIDE }),
                                method: event.target.value as ImputationMethod,
                              })
                            }
                            className="w-56 rounded border border-slate-200 px-2 py-1"
                          >
                            {METHODS.map((item) => (
                              <option
                                key={item.value}
                                value={item.value}
                                disabled={
                                  !row.eligibleMethods.includes(item.value)
                                }
                                title={
                                  row.ineligibleMethodReasons?.[item.value] ??
                                  item.detail
                                }
                              >
                                {item.label}
                              </option>
                            ))}
                          </select>
                        ) : (
                          <span className="font-semibold text-slate-500">
                            No imputation authorized
                          </span>
                        )}
                      </td>
                      <td className="w-[190px] border-b bg-white px-3 py-2 xl:sticky xl:right-[200px] xl:z-10">
                        <div>
                          {override?.method === "PREDICTED"
                            ? "Row-specific · preview not run"
                            : override?.method === "CONSTANT"
                              ? formatValue(override.constantValue)
                              : row.imputedValueOrPolicy}
                        </div>
                        {eligible &&
                        row.descriptivePreviewOnly &&
                        ["MEAN", "MEDIAN", "MODE"].includes(
                          override?.method ??
                            row.selectedImputationMethod ??
                            "",
                        ) ? (
                          <div className="mt-1 text-[9px] font-semibold leading-4 text-amber-700">
                            DESCRIPTIVE PREVIEW · FOLD-LOCAL VALUE WILL DIFFER
                          </div>
                        ) : null}
                      </td>
                      <td className="border-b px-3 py-2">
                        {row.eligibleMethods.map(methodLabel).join(" · ") ||
                          "—"}
                      </td>
                      <td className="border-b px-3 py-2">
                        {formatInteger(row.affectedGames)}
                      </td>
                      <td className="border-b px-3 py-2">
                        {formatInteger(row.affectedBatters)}
                      </td>
                      <td className="border-b px-3 py-2">
                        {formatInteger(row.affectedPitchers)}
                      </td>
                      <td className="border-b px-3 py-2">
                        <div>{row.status}</div>
                        {!eligible && row.exclusionReason ? (
                          <div className="mt-1 max-w-56 text-[9px] leading-4 text-slate-500">
                            {row.exclusionReason}
                          </div>
                        ) : null}
                      </td>
                      <td className="w-[200px] border-b bg-white px-3 py-2 xl:sticky xl:right-0 xl:z-10">
                        <button
                          type="button"
                          disabled={!eligible}
                          onClick={(event) => {
                            if (!eligible) return;
                            detailTrigger.current = event.currentTarget;
                            setActiveRow(row);
                          }}
                          className="inline-flex items-center gap-1 rounded-lg bg-slate-900 px-3 py-1.5 font-semibold text-white disabled:cursor-not-allowed disabled:bg-slate-300"
                        >
                          <Eye size={11} />
                          {eligible ? "View details" : "Not eligible"}
                        </button>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        ) : null}
        <div className="flex items-center justify-between border-t border-slate-100 p-3">
          <button
            type="button"
            disabled={page <= 1}
            onClick={() => setPage((value) => Math.max(1, value - 1))}
            className="inline-flex items-center gap-1 rounded-lg border border-slate-300 px-3 py-1.5 text-xs font-semibold disabled:opacity-40"
          >
            <ChevronLeft size={12} />
            Previous
          </button>
          <span className="text-xs text-slate-500">
            Page {table.value?.data.page ?? page} of{" "}
            {table.value?.data.totalPages ?? "—"}
          </span>
          <button
            type="button"
            disabled={!table.value || page >= table.value.data.totalPages}
            onClick={() => setPage((value) => value + 1)}
            className="inline-flex items-center gap-1 rounded-lg border border-slate-300 px-3 py-1.5 text-xs font-semibold disabled:opacity-40"
          >
            Next
            <ChevronRight size={12} />
          </button>
        </div>
      </section>
      <TreatmentPolicyActions
        kind="missing"
        policy={policy}
        notes={notesValue}
        setNotes={setNotesValue}
        saveStatus={saveMutation.status}
        saveError={saveMutation.error}
        adoptStatus={adoptMutation.status}
        adoptError={adoptMutation.error}
        hasUnsavedChanges={draftHasUnsavedChanges}
        saveDraft={() =>
          void saveMutation.run("policy/draft", policyBody).then((value) => {
            if (value) refreshPolicy();
          })
        }
        adopt={() =>
          void adoptMutation.run("policy/adopt", {
            policyId: policy?.policyId,
            expectedChecksum: policy?.checksum,
          }).then((value) => {
            if (value) refreshPolicy();
          })
        }
        reset={reset}
        compare={compare}
        continueLabel="Continue to Feature Engineering"
        onContinue={() => go("features")}
      />
      <MissingDetailDrawer
        open={Boolean(activeRow)}
        close={() => setActiveRow(null)}
        row={activeRow}
        returnFocusRef={detailTrigger}
        projectId={projectId}
        authority={authority}
        filters={filterState.filters}
        override={effectiveOverride}
        setOverride={(next) =>
          activeRow && setOverride(activeRow.variable, next)
        }
        applyToFamily={() => {
          if (!activeRow || !tableRequest) return;
          const familyName = activeRow.featureFamily;
          void loadAllRows({
            ...tableRequest,
            filters: {},
            search: "",
            families: [familyName],
            coreScope: "",
            dataTypes: [],
            severity: "",
            includeAdvanced: false,
            globalMethod: "DATA_TYPE_AWARE",
            overrides: {},
          }).then((familyRows) => {
            if (!familyRows) return;
            const compatibility = familyRows.map((familyRow) => ({
              row: familyRow,
              failure: familyCompatibilityFailure(familyRow, effectiveOverride),
            }));
            const eligibleRows = compatibility
              .filter((item) => item.failure === null)
              .map((item) => item.row);
            const skipped = familyRows.length - eligibleRows.length;
            const failureSummary = [
              ...new Set(
                compatibility
                  .map((item) => item.failure)
                  .filter((reason): reason is string => Boolean(reason)),
              ),
            ].join("; ");
            setOverrides((current) => ({
              ...current,
              ...Object.fromEntries(
                eligibleRows.map((familyRow) => [
                  familyRow.variable,
                  effectiveOverride,
                ]),
              ),
            }));
            setBulkNotice(
              !eligibleRows.length
                ? `No family overrides were created. Skipped ${skipped} ${familyName} variables: ${failureSummary || "no destination-safe policy could be verified"}.`
                : skipped
                  ? `Applied ${methodLabel(effectiveOverride.method)} to ${eligibleRows.length} eligible ${familyName} variables; skipped ${skipped} variables where that method is invalid.`
                  : `Applied ${methodLabel(effectiveOverride.method)} to all ${eligibleRows.length} eligible ${familyName} variables.`,
            );
          });
        }}
        familyActionMessage={bulkError ?? bulkNotice}
        handoffFeatures={() => {
          if (!activeRow) return;
          setNote(
            "stage3.treatment.featureHandoff",
            JSON.stringify({
              authorityKey: authority,
              variable: activeRow.variable,
              retainIndicator: effectiveOverride.retainIndicator,
              sourceFailureIndicator:
                effectiveOverride.sourceFailureMethod ===
                "RETAIN_WITH_INDICATOR",
              coldStartRule: effectiveOverride.coldStartMethod,
              createdAt: new Date().toISOString(),
            }),
          );
          go("features");
        }}
      />
    </TreatmentStudioShell>
  );
}
