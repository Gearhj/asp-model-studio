import { useEffect, useMemo, useRef, useState } from "react";
import type { EChartsOption } from "echarts";
import {
  AlertTriangle,
  ArrowDown,
  ArrowUp,
  Check,
  ChevronLeft,
  ChevronRight,
  Copy,
  Eye,
  Flag,
  Layers3,
  RefreshCw,
  SlidersHorizontal,
} from "lucide-react";
import EChartsPanel from "../../visual-intelligence/EChartsPanel";
import type { CurrentGoldReviewState } from "../workflow/currentGoldDataReview";
import { CockpitDrawer } from "./CockpitDrawer";
import { useCockpitStore } from "./cockpitApi";
import {
  downloadAggregatedCsv,
  useProjectEdaMetadata,
  type ProjectEdaFilters,
  type ProjectEdaVariable,
} from "./projectEdaApi";
import {
  type OutlierDetail,
  type OutlierDetectionMethod,
  type OutlierOverride,
  type OutlierSummary,
  type OutlierTableRow,
  type OutlierTreatmentMethod,
  type PaginatedTreatmentTable,
  type TreatmentPolicy,
  fetchAllTreatmentRows,
  useTreatmentGet,
  useTreatmentMutation,
  useTreatmentPost,
} from "./projectTreatmentApi";
import {
  DownloadAggregatedButton,
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
} from "./TreatmentStudioShell";

const DETECTION_METHODS: {
  value: OutlierDetectionMethod;
  label: string;
  detail: string;
}[] = [
  { value: "IQR_1_5", label: "IQR 1.5", detail: "Q1 − 1.5×IQR / Q3 + 1.5×IQR" },
  { value: "IQR_3_0", label: "IQR 3.0", detail: "Extreme-outlier sensitivity" },
  {
    value: "P95_UPPER",
    label: "Cap above 95th percentile",
    detail: "Upper-tail detection only: value > P95",
  },
  {
    value: "P99_UPPER",
    label: "Cap above 99th percentile",
    detail: "Upper-tail detection only: value > P99",
  },
  {
    value: "P05_P95",
    label: "Two-sided 5th / 95th percentiles",
    detail: "value < P05 or value > P95",
  },
  {
    value: "P01_P99",
    label: "Two-sided 1st / 99th percentiles",
    detail: "value < P01 or value > P99",
  },
  {
    value: "DOMAIN_BOUNDS",
    label: "Domain / governed bounds",
    detail: "Only registered physical or mathematical bounds",
  },
];
const TREATMENTS: { value: OutlierTreatmentMethod; label: string }[] = [
  { value: "RETAIN", label: "No treatment — retain" },
  { value: "FLAG_ONLY", label: "Flag only" },
  { value: "CAP_IQR", label: "Cap to IQR fences" },
  { value: "WINSORIZE", label: "Winsorization" },
  { value: "CAP_P95", label: "Upper cap at 95th percentile" },
  { value: "CAP_P99", label: "Upper cap at 99th percentile" },
  { value: "SET_MISSING", label: "Set outliers to missing" },
  { value: "EXCLUDE_ROW", label: "Exclude row · advanced/high risk" },
];
const DEFAULT_OVERRIDE: OutlierOverride = {
  detectionMethod: "IQR_1_5",
  treatment: "RETAIN",
  winsorLowerPercentile: 1,
  winsorUpperPercentile: 99,
  included: true,
  notes: "",
};
const PAGE_SIZE = 30;
const OUTLIER_COLUMNS: {
  label: string;
  field: keyof OutlierTableRow | null;
}[] = [
  { label: "NUMBER OF OUTLIERS", field: "numberOfOutliers" },
  { label: "VARIABLE", field: "variable" },
  { label: "OUTLIER %", field: "outlierPercent" },
  { label: "LOWER-TAIL COUNT", field: "lowerTailCount" },
  { label: "UPPER-TAIL COUNT", field: "upperTailCount" },
  { label: "DATA TYPE", field: "dataType" },
  { label: "FEATURE FAMILY", field: "featureFamily" },
  { label: "DEVELOPMENT NONMISSING N", field: "developmentNonmissingN" },
  { label: "MISSING N", field: "missingN" },
  { label: "LOWER THRESHOLD", field: "lowerThreshold" },
  { label: "UPPER THRESHOLD", field: "upperThreshold" },
  { label: "MIN", field: "min" },
  { label: "Q1", field: "q1" },
  { label: "MEDIAN", field: "median" },
  { label: "Q3", field: "q3" },
  { label: "MAX", field: "max" },
  { label: "MEAN", field: "mean" },
  { label: "STANDARD DEVIATION", field: "standardDeviation" },
  { label: "SELECTED DETECTION METHOD", field: "selectedDetectionMethod" },
  { label: "SELECTED TREATMENT", field: "selectedTreatment" },
  { label: "TREATMENT VALUE / BOUNDS", field: "treatmentValueOrBounds" },
  { label: "AFFECTED GAMES", field: "affectedGames" },
  { label: "AFFECTED PLAYERS", field: "affectedPlayers" },
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

function parseHandoff(
  raw: string | undefined,
  key: string,
): {
  selectedVariables: string[];
  filters: ProjectEdaFilters;
  outcomeFilterRemoved: boolean;
} {
  if (!raw)
    return {
      selectedVariables: [],
      filters: {},
      outcomeFilterRemoved: false,
    };
  try {
    const value = JSON.parse(raw) as {
      destination?: string;
      authorityKey?: string;
      selectedVariables?: string[];
      filters?: ProjectEdaFilters;
    };
    if (value.destination !== "outliers" || value.authorityKey !== key) {
      return {
        selectedVariables: [],
        filters: {},
        outcomeFilterRemoved: false,
      };
    }
    const { outcomes, ...safeFilters } = value.filters ?? {};
    return {
      selectedVariables: value.selectedVariables ?? [],
      filters: safeFilters,
      outcomeFilterRemoved: Boolean(outcomes?.length),
    };
  } catch {
    return {
      selectedVariables: [],
      filters: {},
      outcomeFilterRemoved: false,
    };
  }
}

function methodLabel(method: string | null | undefined): string {
  return (
    DETECTION_METHODS.find((item) => item.value === method)?.label ??
    method ??
    "—"
  );
}
function treatmentLabel(method: string | null | undefined): string {
  return (
    TREATMENTS.find((item) => item.value === method)?.label ?? method ?? "—"
  );
}

function outlierPolicyControlSignature(
  globalMethod: string,
  globalTreatment: string | null | undefined,
  overrides: Record<string, OutlierOverride>,
  notes: string,
): string {
  return canonicalPolicySignature({
    globalMethod,
    globalTreatment: globalTreatment ?? "RETAIN",
    overrides: Object.fromEntries(
      Object.entries(overrides).map(([variable, override]) => [
        variable,
        {
          detectionMethod: override.detectionMethod,
          treatment: override.treatment,
          winsorLowerPercentile: override.winsorLowerPercentile,
          winsorUpperPercentile: override.winsorUpperPercentile,
          customLowerThreshold: override.customLowerThreshold,
          customUpperThreshold: override.customUpperThreshold,
          included: override.included,
          notes: override.notes,
        },
      ]),
    ),
    notes: notes.trim(),
  });
}

function isAdvancedOutlierEligible(variable: ProjectEdaVariable): boolean {
  return (
    variable.selectable &&
    variable.dataType === "numeric" &&
    ["PREGAME_FEATURE", "SIMULATION_GENERATED_STATE"].includes(variable.role)
  );
}

function isBinaryOutlierMetadata(variable: ProjectEdaVariable): boolean {
  const name = variable.name;
  const category = variable.category.toUpperCase();
  return (
    variable.role === "MISSINGNESS_INDICATOR" ||
    name.startsWith("is_") ||
    name.toUpperCase().includes("BINARY") ||
    name.endsWith("_indicator") ||
    name.endsWith("_missing") ||
    name.endsWith("_insufficient") ||
    name.startsWith("played_") ||
    name.startsWith("crossed_") ||
    name.startsWith("returned_") ||
    name.startsWith("first_game_") ||
    [
      "same_league_game",
      "interleague_game",
      "division_game",
      "same_division",
      "doubleheader_today",
      "doubleheader_yesterday",
      "previous_game_was_away",
      "previous_game_was_home",
      "repeat_opponent_within_7_days",
      "repeat_opponent_within_14_days",
      "series_rematch_indicator",
      "matchup_batter_bats_left",
      "matchup_batter_bats_switch",
      "matchup_pitcher_throws_left",
      "matchup_platoon_advantage",
    ].includes(name) ||
    category.includes("BINARY")
  );
}

function isDefaultOutlierEligible(variable: ProjectEdaVariable): boolean {
  return (
    isAdvancedOutlierEligible(variable) &&
    variable.role !== "SIMULATION_GENERATED_STATE" &&
    !isBinaryOutlierMetadata(variable)
  );
}

function treatmentDistributionOption(
  detail: OutlierDetail,
  after: boolean,
  mode: "histogram" | "density" | "ecdf",
): EChartsOption {
  const distribution = after ? detail.after : detail.before;
  const thresholds = [detail.thresholds.lower, detail.thresholds.upper].filter(
    (value): value is number => value !== null && Number.isFinite(value),
  );
  const markLine = {
    silent: true,
    symbol: ["none", "none"],
    lineStyle: { color: "#e11d48", type: "dashed" as const },
    data: thresholds.map((value) => ({
      xAxis: value,
      label: { formatter: value.toPrecision(4) },
    })),
  };
  if (distribution.categories) {
    const numericCategories = distribution.categories.every((row) =>
      Number.isFinite(Number(row.value)),
    );
    if (numericCategories) {
      return {
        animationDuration: 220,
        grid: { left: 48, right: 18, top: 18, bottom: 35, containLabel: true },
        tooltip: { trigger: "axis", confine: true },
        xAxis: {
          type: "value",
          min: detail.sharedAxis.minimum ?? undefined,
          max: detail.sharedAxis.maximum ?? undefined,
          name: "Value",
        },
        yAxis: { type: "value", name: "Rows" },
        series: [
          {
            type: "bar",
            barMaxWidth: 38,
            data: distribution.categories.map((row) => [
              Number(row.value),
              row.count,
            ]),
            itemStyle: { color: after ? "#059669" : "#0891b2" },
            markLine,
          },
        ],
      };
    }
    return {
      animationDuration: 220,
      grid: { left: 100, right: 18, top: 18, bottom: 35, containLabel: true },
      tooltip: { trigger: "axis", confine: true },
      xAxis: { type: "value", name: "Rows" },
      yAxis: {
        type: "category",
        data: distribution.categories.map((row) => row.value),
      },
      series: [
        {
          type: "bar",
          data: distribution.categories.map((row) => row.count),
          itemStyle: { color: after ? "#059669" : "#0891b2" },
        },
      ],
    };
  }
  if (mode === "density" && distribution.density?.length)
    return {
      animationDuration: 220,
      grid: { left: 48, right: 18, top: 18, bottom: 36, containLabel: true },
      tooltip: { trigger: "axis", confine: true },
      xAxis: {
        type: "value",
        min: detail.sharedAxis.minimum ?? undefined,
        max: detail.sharedAxis.maximum ?? undefined,
      },
      yAxis: { type: "value", name: "Density" },
      series: [
        {
          type: "line",
          smooth: true,
          symbol: "none",
          areaStyle: { opacity: 0.2 },
          data: distribution.density.map((row) => [row.value, row.density]),
          markLine,
        },
      ],
    };
  if (mode === "ecdf" && distribution.ecdf?.length)
    return {
      animationDuration: 220,
      grid: { left: 48, right: 18, top: 18, bottom: 36, containLabel: true },
      tooltip: { trigger: "axis", confine: true },
      xAxis: {
        type: "value",
        min: detail.sharedAxis.minimum ?? undefined,
        max: detail.sharedAxis.maximum ?? undefined,
      },
      yAxis: { type: "value", name: "Cumulative %", min: 0, max: 100 },
      series: [
        {
          type: "line",
          symbol: "none",
          step: "end",
          data: distribution.ecdf.map((row) => [
            row.value,
            row.cumulativePercent,
          ]),
          markLine,
        },
      ],
    };
  const histogram = distribution.histogram ?? [];
  return {
    animationDuration: 220,
    grid: { left: 48, right: 18, top: 18, bottom: 48, containLabel: true },
    tooltip: { trigger: "axis", confine: true },
    xAxis: {
      type: "value",
      min: detail.sharedAxis.minimum ?? undefined,
      max: detail.sharedAxis.maximum ?? undefined,
      name: "Value",
    },
    yAxis: { type: "value", name: "Rows" },
    series: [
      {
        type: "bar",
        barMaxWidth: 42,
        data: histogram.map((row) => ({
          value: [(row.binStart + row.binEnd) / 2, row.count],
          itemStyle: {
            color: row.affected ? "#e11d48" : after ? "#059669" : "#0891b2",
          },
        })),
        markLine,
      },
    ],
  };
}

function boxPlotOption(detail: OutlierDetail, after: boolean): EChartsOption {
  const box = (after ? detail.after : detail.before).box;
  const values = box ? [box.min, box.q1, box.median, box.q3, box.max] : [];
  const valid = values.length === 5 && values.every((value) => value !== null);
  return {
    animationDuration: 180,
    grid: { left: 54, right: 18, top: 12, bottom: 28, containLabel: true },
    tooltip: { trigger: "item", confine: true },
    xAxis: { type: "category", data: [after ? "After preview" : "Before"] },
    yAxis: {
      type: "value",
      min: detail.sharedAxis.minimum ?? undefined,
      max: detail.sharedAxis.maximum ?? undefined,
      name: "Box plot",
    },
    series: [
      {
        type: "boxplot",
        data: valid ? [values as number[]] : [],
        itemStyle: { color: after ? "#a7f3d0" : "#a5f3fc" },
      },
    ],
  };
}

function OutlierEffectTable({ detail }: { detail: OutlierDetail }) {
  const rows = [
    [
      "Row count",
      formatInteger(detail.effect.originalCount),
      formatInteger(detail.effect.postTreatmentCount),
    ],
    [
      "Min",
      formatValue(detail.effect.original.min),
      formatValue(detail.effect.transformed.min),
    ],
    [
      "Max",
      formatValue(detail.effect.original.max),
      formatValue(detail.effect.transformed.max),
    ],
    [
      "Mean",
      formatValue(detail.effect.original.mean),
      formatValue(detail.effect.transformed.mean),
    ],
    [
      "Median",
      formatValue(detail.effect.original.median),
      formatValue(detail.effect.transformed.median),
    ],
    [
      "Standard deviation",
      formatValue(detail.effect.original.std),
      formatValue(detail.effect.transformed.std),
    ],
  ];
  return (
    <section className="rounded-2xl border border-slate-200 bg-white p-4">
      <h4 className="font-semibold text-slate-950">Treatment effect</h4>
      <div className="mt-3 overflow-auto">
        <table className="w-full min-w-[620px] text-xs">
          <thead>
            <tr className="text-left text-slate-500">
              <th className="border-b px-2 py-2">Measure</th>
              <th className="border-b px-2 py-2">Before</th>
              <th className="border-b px-2 py-2">After preview</th>
            </tr>
          </thead>
          <tbody>
            {rows.map(([label, before, after]) => (
              <tr key={label}>
                <th
                  scope="row"
                  className="border-b px-2 py-2 text-left font-semibold"
                >
                  {label}
                </th>
                <td className="border-b px-2 py-2">{before}</td>
                <td className="border-b px-2 py-2">{after}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <div className="mt-3 grid gap-2 sm:grid-cols-2 xl:grid-cols-5">
        <TreatmentMetric
          label="Changed rows"
          value={formatInteger(detail.effect.changedRows)}
          detail={`${formatInteger(detail.effect.unchangedRows)} unchanged`}
        />
        <TreatmentMetric
          label="Capped low / high"
          value={`${formatInteger(detail.effect.cappedLow)} / ${formatInteger(detail.effect.cappedHigh)}`}
          detail="threshold-derived preview"
        />
        <TreatmentMetric
          label="Excluded"
          value={formatInteger(detail.effect.excluded)}
          detail={`${formatPercent(detail.effect.populationLossPercent)} population loss`}
          tone={detail.effect.excluded ? "rose" : "slate"}
        />
        <TreatmentMetric
          label="Set missing"
          value={formatInteger(detail.effect.setMissing)}
          detail="creates missing-treatment requirement"
          tone={detail.effect.setMissing ? "amber" : "slate"}
        />
        <TreatmentMetric
          label="Games / batters / pitchers"
          value={`${formatInteger(detail.effect.affectedGames)} / ${formatInteger(detail.effect.affectedBatters)} / ${formatInteger(detail.effect.affectedPitchers)}`}
          detail="affected-entity concentration"
        />
      </div>
      <div className="mt-4 overflow-auto">
        <table className="w-full min-w-[680px] text-xs">
          <caption className="mb-2 text-left font-semibold text-slate-800">
            Development-only target-class composition
          </caption>
          <thead>
            <tr className="text-left text-slate-500">
              <th className="border-b px-2 py-2">Target class</th>
              <th className="border-b px-2 py-2">Before count</th>
              <th className="border-b px-2 py-2">Before %</th>
              <th className="border-b px-2 py-2">After count</th>
              <th className="border-b px-2 py-2">After %</th>
            </tr>
          </thead>
          <tbody>
            {[
              ...new Set([
                ...detail.effect.targetCompositionBefore.map(
                  (row) => row.value,
                ),
                ...detail.effect.targetCompositionAfter.map((row) => row.value),
              ]),
            ].map((value) => {
              const before = detail.effect.targetCompositionBefore.find(
                (row) => row.value === value,
              );
              const after = detail.effect.targetCompositionAfter.find(
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
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
      <p className="mt-3 rounded-lg bg-slate-50 p-3 font-mono text-[11px] text-slate-700">
        {detail.effect.formula}
      </p>
    </section>
  );
}

function OutlierDetailDrawer({
  open,
  close,
  row,
  returnFocusRef,
  projectId,
  authority,
  filters,
  override,
  setOverride,
  copyToFamily,
  familyActionMessage,
}: {
  open: boolean;
  close: () => void;
  row: OutlierTableRow | null;
  returnFocusRef: React.RefObject<HTMLElement>;
  projectId: string;
  authority: string;
  filters: ProjectEdaFilters;
  override: OutlierOverride;
  setOverride: (override: OutlierOverride) => void;
  copyToFamily: () => void;
  familyActionMessage: string | null;
}) {
  const [mode, setMode] = useState<"histogram" | "density" | "ecdf">(
    "histogram",
  );
  const request = useMemo(
    () =>
      row
        ? {
            variable: row.variable,
            filters,
            detectionMethod: override.detectionMethod,
            treatment: override.treatment,
            winsorLowerPercentile: override.winsorLowerPercentile,
            winsorUpperPercentile: override.winsorUpperPercentile,
            customLowerThreshold: override.customLowerThreshold,
            customUpperThreshold: override.customUpperThreshold,
            included: override.included,
            notes: override.notes,
          }
        : null,
    [filters, override, row],
  );
  const preview = useTreatmentPost<OutlierDetail>(
    projectId,
    authority,
    "outliers",
    "preview",
    request,
  );
  const detail = preview.value?.data ?? null;
  return (
    <CockpitDrawer
      open={open}
      onClose={close}
      returnFocusRef={returnFocusRef}
      title={row ? `Outlier analysis · ${row.variable}` : "Outlier analysis"}
      eyebrow="Development-only descriptive preview"
      description="Before and after use identical bins, axes, filters, and population semantics. Fold-local thresholds will be refit later."
      widthClassName="max-w-none"
      testId="stage3-outlier-detail"
    >
      <div className="space-y-4 p-4 sm:p-6">
        <section className="grid gap-3 rounded-2xl border border-slate-200 bg-white p-4 lg:grid-cols-5">
          <label className="text-[10px] font-semibold uppercase text-slate-500">
            Detection method
            <select
              value={override.detectionMethod}
              onChange={(event) =>
                setOverride({
                  ...override,
                  detectionMethod: event.target.value as OutlierDetectionMethod,
                })
              }
              className="mt-1 block w-full rounded-lg border border-slate-300 px-2 py-2 text-xs font-normal normal-case"
            >
              {DETECTION_METHODS.map((item) => (
                <option
                  key={item.value}
                  value={item.value}
                  disabled={
                    row
                      ? !row.eligibleDetectionMethods.includes(item.value)
                      : false
                  }
                >
                  {item.label}
                </option>
              ))}
            </select>
          </label>
          <label className="text-[10px] font-semibold uppercase text-slate-500">
            Treatment
            <select
              value={override.treatment}
              onChange={(event) =>
                setOverride({
                  ...override,
                  treatment: event.target.value as OutlierTreatmentMethod,
                })
              }
              className="mt-1 block w-full rounded-lg border border-slate-300 px-2 py-2 text-xs font-normal normal-case"
            >
              {TREATMENTS.map((item) => (
                <option
                  key={item.value}
                  value={item.value}
                  disabled={
                    row ? !row.eligibleTreatments.includes(item.value) : false
                  }
                >
                  {item.label}
                </option>
              ))}
            </select>
          </label>
          <label className="text-[10px] font-semibold uppercase text-slate-500">
            Winsor lower %
            <input
              type="number"
              min={0}
              max={49}
              value={override.winsorLowerPercentile ?? 1}
              disabled={override.treatment !== "WINSORIZE"}
              onChange={(event) =>
                setOverride({
                  ...override,
                  winsorLowerPercentile: Number(event.target.value),
                })
              }
              className="mt-1 block w-full rounded-lg border border-slate-300 px-2 py-2 text-xs font-normal disabled:bg-slate-100"
            />
          </label>
          <label className="text-[10px] font-semibold uppercase text-slate-500">
            Winsor upper %
            <input
              type="number"
              min={51}
              max={100}
              value={override.winsorUpperPercentile ?? 99}
              disabled={override.treatment !== "WINSORIZE"}
              onChange={(event) =>
                setOverride({
                  ...override,
                  winsorUpperPercentile: Number(event.target.value),
                })
              }
              className="mt-1 block w-full rounded-lg border border-slate-300 px-2 py-2 text-xs font-normal disabled:bg-slate-100"
            />
          </label>
          <label className="text-[10px] font-semibold uppercase text-slate-500">
            Custom lower threshold
            <input
              type="number"
              value={override.customLowerThreshold ?? ""}
              placeholder="Use governed method"
              onChange={(event) =>
                setOverride({
                  ...override,
                  customLowerThreshold:
                    event.target.value === ""
                      ? null
                      : Number(event.target.value),
                })
              }
              className="mt-1 block w-full rounded-lg border border-slate-300 px-2 py-2 text-xs font-normal normal-case"
            />
          </label>
          <label className="text-[10px] font-semibold uppercase text-slate-500">
            Custom upper threshold
            <input
              type="number"
              value={override.customUpperThreshold ?? ""}
              placeholder="Use governed method"
              onChange={(event) =>
                setOverride({
                  ...override,
                  customUpperThreshold:
                    event.target.value === ""
                      ? null
                      : Number(event.target.value),
                })
              }
              className="mt-1 block w-full rounded-lg border border-slate-300 px-2 py-2 text-xs font-normal normal-case"
            />
          </label>
          <label className="flex items-center gap-2 self-end rounded-lg border border-slate-200 px-3 py-2 text-xs font-semibold text-slate-700">
            <input
              type="checkbox"
              checked={override.included ?? true}
              onChange={(event) =>
                setOverride({ ...override, included: event.target.checked })
              }
            />
            Include variable in policy
          </label>
          <label className="text-[10px] font-semibold uppercase text-slate-500">
            Chart
            <select
              value={mode}
              onChange={(event) => setMode(event.target.value as typeof mode)}
              className="mt-1 block w-full rounded-lg border border-slate-300 px-2 py-2 text-xs font-normal normal-case"
            >
              <option value="histogram">Histogram / frequency</option>
              <option value="density">Density</option>
              <option value="ecdf">ECDF</option>
            </select>
          </label>
          <label className="lg:col-span-4 text-[10px] font-semibold uppercase text-slate-500">
            Variable notes
            <input
              value={override.notes ?? ""}
              onChange={(event) =>
                setOverride({ ...override, notes: event.target.value })
              }
              className="mt-1 block w-full rounded-lg border border-slate-300 px-3 py-2 text-xs font-normal normal-case"
            />
          </label>
          <div className="flex items-end gap-2">
            <button
              type="button"
              onClick={copyToFamily}
              className="inline-flex items-center gap-1 rounded-lg border border-slate-300 px-3 py-2 text-xs font-semibold text-slate-700"
            >
              <Copy size={12} />
              Copy to family
            </button>
          </div>
        </section>
        {override.treatment === "SET_MISSING" ? (
          <div
            role="status"
            className="rounded-lg border border-amber-300 bg-amber-50 p-3 text-xs leading-5 text-amber-950"
          >
            A pending Missing-Value Studio requirement is recorded automatically
            for this variable. This preview does not activate imputation.
          </div>
        ) : null}
        {familyActionMessage ? (
          <div
            role="status"
            className="rounded-lg border border-cyan-200 bg-cyan-50 p-3 text-xs text-cyan-950"
          >
            {familyActionMessage}
          </div>
        ) : null}
        {override.treatment === "EXCLUDE_ROW" ? (
          <div className="rounded-xl border border-rose-300 bg-rose-50 p-4 text-xs leading-5 text-rose-950">
            <AlertTriangle size={15} className="mr-1 inline" />
            <b>High-risk row exclusion:</b> inspect exact population loss,
            affected games, target composition, and player concentration below.
            An IQR flag alone is not a reason to delete modeling rows.
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
              <Flag size={14} />
              <b>{detail.previewLabel}</b>
              <span>{detail.thresholds.formula}</span>
              <span className="ml-auto font-semibold">
                DESCRIPTIVE PREVIEW — FOLD-LOCAL VALUES WILL DIFFER
              </span>
            </div>
            <div className="grid gap-4 xl:grid-cols-2">
              <section className="rounded-2xl border border-slate-200 bg-white p-4">
                <h4 className="font-semibold text-slate-950">
                  Before treatment
                </h4>
                <p className="mt-1 text-xs text-slate-500">
                  Original Current Gold values ·{" "}
                  {formatInteger(detail.before.observedCount)} observed ·{" "}
                  {formatInteger(detail.before.missingCount)} missing
                </p>
                <EChartsPanel
                  option={treatmentDistributionOption(detail, false, mode)}
                  height={340}
                  ariaLabel={`Before outlier treatment ${row?.variable}`}
                />
                <EChartsPanel
                  option={boxPlotOption(detail, false)}
                  height={150}
                  ariaLabel={`Before-treatment box plot ${row?.variable}`}
                />
              </section>
              <section className="rounded-2xl border border-emerald-200 bg-white p-4">
                <h4 className="font-semibold text-slate-950">
                  After treatment preview
                </h4>
                <p className="mt-1 text-xs text-slate-500">
                  {["RETAIN", "FLAG_ONLY"].includes(detail.treatment)
                    ? "Distribution unchanged by design; flags preserve original values."
                    : "Preview transformation only; Gold remains unchanged."}
                </p>
                <EChartsPanel
                  option={treatmentDistributionOption(detail, true, mode)}
                  height={340}
                  ariaLabel={`After outlier treatment ${row?.variable}`}
                />
                <EChartsPanel
                  option={boxPlotOption(detail, true)}
                  height={150}
                  ariaLabel={`After-treatment box plot ${row?.variable}`}
                />
              </section>
            </div>
            <OutlierEffectTable detail={detail} />
          </>
        ) : null}
      </div>
    </CockpitDrawer>
  );
}

export function ProjectBoundOutlierStudio({
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
    () => parseHandoff(notes["stage3.eda.handoff"], authority),
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
  const [globalDetection, setGlobalDetection] =
    useState<OutlierDetectionMethod>("IQR_1_5");
  const [globalTreatment, setGlobalTreatment] =
    useState<OutlierTreatmentMethod>("RETAIN");
  const [overrides, setOverrides] = useState<Record<string, OutlierOverride>>(
    {},
  );
  const [selected, setSelected] = useState<string[]>(handoff.selectedVariables);
  const [activeRow, setActiveRow] = useState<OutlierTableRow | null>(null);
  const [sort, setSort] = useState({
    field: "numberOfOutliers",
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
  const hydrated = useRef(false);
  const enabled = state.status === "ready" && Boolean(review);
  const metadata = useProjectEdaMetadata(projectId, authority, enabled);
  const pendingMissingRequirements = useMemo(() => {
    const catalogVariables = metadata.value
      ? [
          ...new Set([
            ...metadata.value.data.variables
              .filter(isDefaultOutlierEligible)
              .map((variable) => variable.name),
            ...metadata.value.data.variables
              .filter(
                (variable) =>
                  !isDefaultOutlierEligible(variable) &&
                  isAdvancedOutlierEligible(variable) &&
                  Boolean(overrides[variable.name]),
              )
              .map((variable) => variable.name),
          ]),
        ]
      : [];
    return catalogVariables
      .flatMap((variable) => {
        const explicit = overrides[variable];
        const outlierPolicy = explicit ?? {
          ...DEFAULT_OVERRIDE,
          detectionMethod: globalDetection,
          treatment: globalTreatment,
        };
        return outlierPolicy.treatment === "SET_MISSING" &&
          (outlierPolicy.included ?? true)
          ? [
              {
                variable,
                reason: "OUTLIER_SET_TO_MISSING",
                outlierPolicy,
              },
            ]
          : [];
      })
      .sort((left, right) => left.variable.localeCompare(right.variable));
  }, [globalDetection, globalTreatment, metadata.value, overrides]);
  useEffect(() => {
    const key = "stage3.treatment.pendingMissing";
    const next = JSON.stringify({
      authorityKey: authority,
      requirements: pendingMissingRequirements,
    });
    if (notes[key] !== next) setNote(key, next);
  }, [authority, notes, pendingMissingRequirements, setNote]);
  const summary = useTreatmentGet<OutlierSummary>(
    projectId,
    authority,
    "outliers",
    "summary",
    enabled,
    refreshKey,
  );
  const policyQuery = useTreatmentGet<TreatmentPolicy<OutlierOverride>>(
    projectId,
    authority,
    "outliers",
    "policy",
    enabled,
    refreshKey,
  );
  const policy = policyQuery.value?.data ?? summary.value?.data.policy ?? null;
  useEffect(() => {
    if (!policy || hydrated.current) return;
    hydrated.current = true;
    if (policy.globalMethod)
      setGlobalDetection(policy.globalMethod as OutlierDetectionMethod);
    if (policy.globalTreatment)
      setGlobalTreatment(policy.globalTreatment as OutlierTreatmentMethod);
    setOverrides(policy.overrides ?? {});
    setNotesValue(policy.notes ?? "");
  }, [policy]);
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
            globalMethod: globalDetection,
            globalTreatment,
            overrides,
            policyVersion: policy?.policyVersion ?? null,
          }
        : null,
    [
      authority,
      enabled,
      filterState,
      globalDetection,
      globalTreatment,
      overrides,
      page,
      policy?.policyVersion,
      sort,
    ],
  );
  const table = useTreatmentPost<PaginatedTreatmentTable<OutlierTableRow>>(
    projectId,
    authority,
    "outliers",
    "table",
    tableRequest,
  );
  const saveMutation = useTreatmentMutation<{
    policy: TreatmentPolicy<OutlierOverride>;
  }>(projectId, authority, "outliers");
  const adoptMutation = useTreatmentMutation<{
    policy: TreatmentPolicy<OutlierOverride>;
  }>(projectId, authority, "outliers");
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
  const activeSummaryData = table.value?.data.activeSummary ?? summaryData;
  const effectiveOverride = activeRow
    ? (overrides[activeRow.variable] ?? {
        ...DEFAULT_OVERRIDE,
        detectionMethod: activeRow.selectedDetectionMethod ?? globalDetection,
        treatment: activeRow.selectedTreatment ?? globalTreatment,
      })
    : DEFAULT_OVERRIDE;
  const setOverride = (variable: string, next: OutlierOverride) =>
    setOverrides((current) => ({ ...current, [variable]: next }));
  const policyBody = {
    policyId: policy?.policyId ?? undefined,
    projectId,
    goldManifestSha: review.goldAuthority.manifestSha,
    developmentCutoff: review.matrix.development.endDate,
    finalOotIdentity: `${review.matrix.finalOot.startDate}:${review.matrix.finalOot.endDate}:${review.matrix.finalOot.rows}`,
    globalMethod: globalDetection,
    globalTreatment,
    overrides,
    notes: notesValue,
    fittingRule: "FIT_THRESHOLDS_INSIDE_EACH_CHRONOLOGICAL_TRAINING_FOLD",
  };
  const draftHasUnsavedChanges =
    policy?.status === "DRAFT" &&
    outlierPolicyControlSignature(
      globalDetection,
      globalTreatment,
      overrides,
      notesValue,
    ) !==
      outlierPolicyControlSignature(
        policy.globalMethod,
        policy.globalTreatment,
        policy.overrides,
        policy.notes,
      );
  const refreshPolicy = () => {
    hydrated.current = false;
    setRefreshKey((value) => value + 1);
  };
  const reset = () => {
    setGlobalDetection("IQR_1_5");
    setGlobalTreatment("RETAIN");
    setOverrides({});
    setSelected([]);
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
      const result = await fetchAllTreatmentRows<OutlierTableRow>(
        projectId,
        authority,
        "outliers",
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
  const summaryTitle =
    table.status !== "ready"
      ? "Analysis not yet run"
      : activeSummaryData?.status === "NO_OUTLIERS"
        ? "No outliers under the active governed method"
        : activeSummaryData?.status === "ANALYZED"
          ? "Outliers found — treatment remains preview only"
          : "No treatment adopted";
  const compare = (
    <div className="grid gap-3 sm:grid-cols-2">
      <TreatmentMetric
        label="Current preview"
        value={`${methodLabel(globalDetection)} · ${treatmentLabel(globalTreatment)}`}
        detail={`${Object.keys(overrides).length} per-variable overrides`}
        tone="cyan"
      />
      <TreatmentMetric
        label="Saved policy"
        value={
          policy
            ? `${methodLabel(policy.globalMethod)} · ${treatmentLabel(policy.globalTreatment)}`
            : "Unavailable"
        }
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
      kind="outliers"
      review={review}
      title="Project-bound Outlier Treatment Studio"
      description="Detect, compare, and version outlier fitting rules on the accepted Current Gold development population without modifying registered values."
      policy={policy}
    >
      <TreatmentDecisionHeader
        kind="outliers"
        status={summary.status}
        summary={summaryTitle}
      >
        <div className="grid gap-2 sm:grid-cols-2 xl:grid-cols-6">
          <TreatmentMetric
            label="Active preview"
            value={`${methodLabel(globalDetection)} · ${treatmentLabel(globalTreatment)}`}
            detail={`${formatInteger(activeSummaryData?.eligibleVariables)} eligible predictors under current filters`}
            tone="cyan"
          />
          <TreatmentMetric
            label="Predictors with outliers"
            value={formatInteger(activeSummaryData?.variablesWithOutliers)}
            detail={`${methodLabel(activeSummaryData?.activeDetectionMethod ?? globalDetection)} · ${treatmentLabel(activeSummaryData?.activeTreatment ?? globalTreatment)}`}
            tone="amber"
          />
          <TreatmentMetric
            label="Affected development rows"
            value={formatInteger(activeSummaryData?.totalAffectedRows)}
            detail={`${formatInteger(activeSummaryData?.affectedGames)} games`}
          />
          <TreatmentMetric
            label="Batters / pitchers"
            value={`${formatInteger(activeSummaryData?.affectedBatters)} / ${formatInteger(activeSummaryData?.affectedPitchers)}`}
            detail="Unique affected entities"
          />
          <TreatmentMetric
            label="Highest affected"
            value={activeSummaryData?.highestAffectedVariable ?? "—"}
            detail={`${formatInteger(activeSummaryData?.highestAffectedCount)} rows · ${formatPercent(activeSummaryData?.highestAffectedPercent)}`}
            tone="amber"
          />
          <TreatmentMetric
            label="Policy"
            value={policy?.status ?? "NO TREATMENT ADOPTED"}
            detail={`Version ${policy?.policyVersion ?? "—"} · OOT LOCKED`}
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
          { value: "AFFECTED", label: "Has detected outliers" },
          { value: "HIGH", label: "High affected percentage" },
          { value: "NONE", label: "No detected outliers" },
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
          <b>Outcome-class filter removed.</b> Outlier thresholds and treatment
          previews cannot be conditioned on the target outcome. All other
          authorized development-only handoff filters were preserved.
        </div>
      ) : null}
      <section
        className="rounded-2xl border border-slate-200 bg-white p-4 shadow-sm"
        data-testid="stage3-outlier-global-policy"
      >
        <div className="flex flex-wrap items-end gap-3">
          <label className="min-w-56 text-[10px] font-semibold uppercase text-slate-500">
            Global detection method
            <select
              aria-label="Global outlier detection method"
              value={globalDetection}
              onChange={(event) => {
                setGlobalDetection(
                  event.target.value as OutlierDetectionMethod,
                );
                setPage(1);
              }}
              className="mt-1 block w-full rounded-lg border border-slate-300 px-3 py-2 text-xs font-normal normal-case"
            >
              {DETECTION_METHODS.map((item) => (
                <option key={item.value} value={item.value}>
                  {item.label}
                </option>
              ))}
            </select>
          </label>
          <label className="min-w-56 text-[10px] font-semibold uppercase text-slate-500">
            Global treatment preview
            <select
              aria-label="Global outlier treatment"
              value={globalTreatment}
              onChange={(event) =>
                setGlobalTreatment(event.target.value as OutlierTreatmentMethod)
              }
              className="mt-1 block w-full rounded-lg border border-slate-300 px-3 py-2 text-xs font-normal normal-case"
            >
              {TREATMENTS.map((item) => (
                <option key={item.value} value={item.value}>
                  {item.label}
                </option>
              ))}
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
                includeAdvanced: true,
                globalMethod: "IQR_1_5",
                globalTreatment: "RETAIN",
                overrides: {},
              }).then((allRows) => {
                if (!allRows) return;
                const eligibleRows = allRows.filter(
                  (row) =>
                    row.eligible &&
                    selected.includes(row.variable) &&
                    row.eligibleDetectionMethods.includes(globalDetection) &&
                    row.eligibleTreatments.includes(globalTreatment),
                );
                const skipped = selected.length - eligibleRows.length;
                setOverrides((current) => ({
                  ...current,
                  ...Object.fromEntries(
                    eligibleRows.map((row) => [
                      row.variable,
                      {
                        ...DEFAULT_OVERRIDE,
                        detectionMethod: globalDetection,
                        treatment: globalTreatment,
                      },
                    ]),
                  ),
                }));
                setBulkNotice(
                  skipped
                    ? `Applied the global outlier proposal to ${eligibleRows.length} selected variables; skipped ${skipped} unavailable or method-ineligible selections.`
                    : `Applied the global outlier proposal to all ${eligibleRows.length} selected variables.`,
                );
              });
            }}
            className="rounded-lg border border-slate-300 px-3 py-2 text-xs font-semibold text-slate-700 disabled:opacity-40"
          >
            Apply to selected
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
          <span className="ml-auto max-w-md text-[10px] leading-4 text-slate-500">
            {
              DETECTION_METHODS.find((item) => item.value === globalDetection)
                ?.detail
            }
            . Every preview change reissues an authority-bound aggregate query.
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
        data-testid="stage3-outlier-summary-table"
      >
        <div className="flex flex-wrap items-center gap-2 border-b border-slate-100 p-4">
          <div>
            <h3 className="font-semibold text-slate-950">
              Eligible predictor outlier table
            </h3>
            <p className="mt-1 text-xs text-slate-500">
              Default order: highest detected outlier count first. Aggregated
              table only; raw-row bulk export is disabled. Advanced inspection
              appends read-only excluded metadata rows with no diagnostics.
            </p>
          </div>
          <span className="ml-auto text-xs text-slate-500">
            {formatInteger(table.value?.data.totalRows)} variables ·{" "}
            {formatInteger(table.value?.data.excludedMetadataRows)} read-only
          </span>
          <DownloadAggregatedButton
            disabled={!tableRequest || bulkStatus === "loading"}
            onClick={() => {
              if (!tableRequest) return;
              void loadAllRows(tableRequest).then((allRows) => {
                if (allRows)
                  downloadAggregatedCsv(
                    "project-bound-outlier-table.csv",
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
            <table className="min-w-[3100px] text-[11px]">
              <thead className="sticky top-0 z-20 bg-slate-100 text-left text-[9px] uppercase tracking-wide text-slate-500">
                <tr>
                  {OUTLIER_COLUMNS.map(({ label, field }, index) => (
                    <th
                      key={label}
                      className={`border-b px-3 py-2 ${index < 2 ? "sticky z-30 bg-slate-100" : ""}`}
                      style={
                        index === 0
                          ? { left: 0 }
                          : index === 1
                            ? { left: 150 }
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
                      <td className="sticky left-0 z-10 w-[150px] border-b bg-white px-3 py-2">
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
                            {formatInteger(row.numberOfOutliers)}
                          </b>
                        </label>
                      </td>
                      <td className="sticky left-[150px] z-10 w-[230px] border-b bg-white px-3 py-2 font-mono font-semibold text-slate-900">
                        {row.variable}
                        {override || row.override ? (
                          <span className="ml-2 rounded bg-cyan-100 px-1.5 py-0.5 font-sans text-[8px] text-cyan-800">
                            OVERRIDE
                          </span>
                        ) : null}
                      </td>
                      <td className="border-b px-3 py-2">
                        {formatPercent(row.outlierPercent)}
                      </td>
                      <td className="border-b px-3 py-2">
                        {formatInteger(row.lowerTailCount)}
                      </td>
                      <td className="border-b px-3 py-2">
                        {formatInteger(row.upperTailCount)}
                      </td>
                      <td className="border-b px-3 py-2">{row.dataType}</td>
                      <td className="border-b px-3 py-2">
                        {row.featureFamily}
                      </td>
                      <td className="border-b px-3 py-2">
                        {formatInteger(row.developmentNonmissingN)}
                      </td>
                      <td className="border-b px-3 py-2">
                        {formatInteger(row.missingN)}
                      </td>
                      <td className="border-b px-3 py-2">
                        {formatValue(row.lowerThreshold)}
                      </td>
                      <td className="border-b px-3 py-2">
                        {formatValue(row.upperThreshold)}
                      </td>
                      {[
                        row.min,
                        row.q1,
                        row.median,
                        row.q3,
                        row.max,
                        row.mean,
                        row.standardDeviation,
                      ].map((value, index) => (
                        <td key={index} className="border-b px-3 py-2">
                          {formatValue(value)}
                        </td>
                      ))}
                      <td className="sticky right-[420px] z-10 border-b bg-white px-3 py-2">
                        {eligible ? (
                          <select
                            aria-label={`Detection method for ${row.variable}`}
                            value={
                              override?.detectionMethod ??
                              row.selectedDetectionMethod ??
                              "IQR_1_5"
                            }
                            onChange={(event) =>
                              setOverride(row.variable, {
                                ...(override ?? {
                                  ...DEFAULT_OVERRIDE,
                                  treatment: row.selectedTreatment ?? "RETAIN",
                                }),
                                detectionMethod: event.target
                                  .value as OutlierDetectionMethod,
                              })
                            }
                            className="w-48 rounded border border-slate-200 px-2 py-1"
                          >
                            {DETECTION_METHODS.map((item) => (
                              <option
                                key={item.value}
                                value={item.value}
                                disabled={
                                  !row.eligibleDetectionMethods.includes(
                                    item.value,
                                  )
                                }
                              >
                                {item.label}
                              </option>
                            ))}
                          </select>
                        ) : (
                          <span className="font-semibold text-slate-500">
                            Read-only metadata
                          </span>
                        )}
                      </td>
                      <td className="sticky right-[210px] z-10 border-b bg-white px-3 py-2">
                        {eligible ? (
                          <select
                            aria-label={`Treatment for ${row.variable}`}
                            value={
                              override?.treatment ??
                              row.selectedTreatment ??
                              "RETAIN"
                            }
                            onChange={(event) =>
                              setOverride(row.variable, {
                                ...(override ?? {
                                  ...DEFAULT_OVERRIDE,
                                  detectionMethod:
                                    row.selectedDetectionMethod ?? "IQR_1_5",
                                }),
                                treatment: event.target
                                  .value as OutlierTreatmentMethod,
                              })
                            }
                            className="w-48 rounded border border-slate-200 px-2 py-1"
                          >
                            {TREATMENTS.map((item) => (
                              <option
                                key={item.value}
                                value={item.value}
                                disabled={
                                  !row.eligibleTreatments.includes(item.value)
                                }
                              >
                                {item.label}
                              </option>
                            ))}
                          </select>
                        ) : (
                          <span className="font-semibold text-slate-500">
                            No treatment authorized
                          </span>
                        )}
                      </td>
                      <td className="border-b px-3 py-2">
                        {row.treatmentValueOrBounds}
                      </td>
                      <td className="border-b px-3 py-2">
                        {formatInteger(row.affectedGames)}
                      </td>
                      <td className="border-b px-3 py-2">
                        {formatInteger(row.affectedPlayers)}
                      </td>
                      <td className="border-b px-3 py-2">
                        <div>{row.status}</div>
                        {!eligible && row.exclusionReason ? (
                          <div className="mt-1 max-w-56 text-[9px] leading-4 text-slate-500">
                            {row.exclusionReason}
                          </div>
                        ) : null}
                      </td>
                      <td className="sticky right-0 z-10 w-[210px] border-b bg-white px-3 py-2">
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
        kind="outliers"
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
          void adoptMutation.run("policy/adopt", policyBody).then((value) => {
            if (value) refreshPolicy();
          })
        }
        reset={reset}
        compare={compare}
        continueLabel="Continue to Missing Values"
        onContinue={() => go("missing")}
      />
      <OutlierDetailDrawer
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
        copyToFamily={() => {
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
            includeAdvanced: true,
            globalMethod: "IQR_1_5",
            globalTreatment: "RETAIN",
            overrides: {},
          }).then((familyRows) => {
            if (!familyRows) return;
            const eligibleRows = familyRows.filter(
              (familyRow) =>
                familyRow.eligible &&
                familyRow.eligibleDetectionMethods.includes(
                  effectiveOverride.detectionMethod,
                ),
            );
            const skipped = familyRows.length - eligibleRows.length;
            setOverrides((current) => {
              const familyMethodOverrides = Object.fromEntries(
                eligibleRows.map((familyRow) => [
                  familyRow.variable,
                  {
                    ...(current[familyRow.variable] ?? {
                      ...DEFAULT_OVERRIDE,
                      detectionMethod: globalDetection,
                      treatment: globalTreatment,
                    }),
                    detectionMethod: effectiveOverride.detectionMethod,
                  },
                ]),
              );
              return { ...current, ...familyMethodOverrides };
            });
            setBulkNotice(
              skipped
                ? `Copied ${methodLabel(effectiveOverride.detectionMethod)} to ${eligibleRows.length} eligible ${familyName} variables; skipped ${skipped} variables where that detection method is invalid.`
                : `Copied ${methodLabel(effectiveOverride.detectionMethod)} to all ${eligibleRows.length} eligible ${familyName} variables. Existing treatments and variable-specific bounds were preserved.`,
            );
          });
        }}
        familyActionMessage={bulkError ?? bulkNotice}
      />
    </TreatmentStudioShell>
  );
}
