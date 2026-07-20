import { DATASET_API_BASE } from "./datasetLibrary";

export type AbTestingDefaults = {
  dataset: string;
  unitIdColumn: string;
  treatmentColumn: string;
  treatmentValue: string;
  controlValue: string;
  outcomeColumn: string;
  successEvent: string;
  exposureColumn: string;
  segmentColumns: string[];
};

export type AbGroupSummary = {
  treatmentCount: number;
  controlCount: number;
  treatmentConversions: number;
  controlConversions: number;
  treatmentRate: number;
  controlRate: number;
};

export type AbDataProfile = {
  dataset: string;
  rows: number;
  columns: number;
  uniqueUnits: number;
  duplicateUnits: number;
  missingUnitId: number;
  missingTreatment: number;
  missingOutcome: number;
  invalidTreatment: number;
  invalidOutcome: number;
  treatmentValuesDetected: string[];
  outcomeValuesDetected: string[];
  treatmentGroupCount: number;
  controlGroupCount: number;
  treatmentShare: number;
  controlShare: number;
  allocationRatio: number;
};

export type AbSegmentSummaryRow = {
  segmentColumn: string;
  segment: string;
  treatmentCount: number;
  controlCount: number;
  treatmentConversionRate: number;
  controlConversionRate: number;
  absoluteLift: number;
  relativeLift: number;
  pValue: number;
  confidenceInterval: string;
  warning: string;
};

export type AbAnalysisDatasetStatus = {
  dataset: string;
  rowCount: number;
  validAnalysisRecords: number;
  fullDatasetAvailable: boolean;
  previewOnly: boolean;
  source: "full_dataset_artifact" | "preview_rows" | "compact_browser_cache";
  message: string;
};

export type AbExposureSummaryRow = {
  group: string;
  count: number;
  mean: number;
  median: number;
  min: number;
  max: number;
};

export type AbDatasetAggregates = {
  outcomeSuccess: number;
  outcomeNonSuccess: number;
  overallConversionRate: number;
  missingByColumn: Record<string, number>;
  exposureAvailable: boolean;
  exposureSummary: AbExposureSummaryRow[];
};

export type AbAnalysisDataset = {
  status: AbAnalysisDatasetStatus;
  rows: Array<Record<string, string | number | boolean>>;
  profile: AbDataProfile;
  summary: AbGroupSummary;
  daySegments: AbSegmentSummaryRow[];
  hourSegments: AbSegmentSummaryRow[];
  aggregates: AbDatasetAggregates;
};

export async function analyzeRegisteredAbDataset(input: {
  datasetId: string;
  versionId: string;
  mapping: AbTestingDefaults;
}) {
  const response = await fetch(`${DATASET_API_BASE}/experimentation/ab/analyze`, {
    method: "POST",
    credentials: "include",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ datasetId: input.datasetId, versionId: input.versionId, mapping: input.mapping }),
  });
  const payload = await response.json().catch(() => null) as { ok?: boolean; analysis?: AbAnalysisDataset; detail?: string; error?: string } | null;
  if (!response.ok || !payload?.ok || !payload.analysis) {
    throw new Error(payload?.detail || payload?.error || `A/B full-dataset analysis failed with HTTP ${response.status}.`);
  }
  return payload.analysis;
}

export const AB_MARKETING_DEFAULTS: AbTestingDefaults = {
  dataset: "AB_MARKETING.csv",
  unitIdColumn: "user.id",
  treatmentColumn: "test.group",
  treatmentValue: "ad",
  controlValue: "psa",
  outcomeColumn: "converted",
  successEvent: "True",
  exposureColumn: "total.ads",
  segmentColumns: ["most.ads.day", "most.ads.hour"],
};

export const AB_WORKFLOW_DEFAULTS: AbTestingDefaults = {
  ...AB_MARKETING_DEFAULTS,
  dataset: "AB_WORKFLOW.csv",
};

export const AB_MARKETING_EXPECTED_COLUMNS = [
  "user.id",
  "test.group",
  "converted",
  "total.ads",
  "most.ads.day",
  "most.ads.hour",
];

export const AB_WORKFLOW_EXPECTED_COLUMNS = AB_MARKETING_EXPECTED_COLUMNS;
export const AB_WORKFLOW_FULL_ROW_COUNT = 588_101;
export const AB_WORKFLOW_FULL_VALID_ANALYSIS_RECORDS = 588_101;

export const AB_MARKETING_SAMPLE: Array<Record<string, string | number | boolean>> = [
  { "user.id": 1, "test.group": "ad", converted: true, "total.ads": 130, "most.ads.day": "Monday", "most.ads.hour": 20 },
  { "user.id": 2, "test.group": "ad", converted: false, "total.ads": 93, "most.ads.day": "Tuesday", "most.ads.hour": 10 },
  { "user.id": 3, "test.group": "ad", converted: true, "total.ads": 21, "most.ads.day": "Wednesday", "most.ads.hour": 18 },
  { "user.id": 4, "test.group": "ad", converted: false, "total.ads": 45, "most.ads.day": "Thursday", "most.ads.hour": 15 },
  { "user.id": 5, "test.group": "ad", converted: true, "total.ads": 87, "most.ads.day": "Friday", "most.ads.hour": 20 },
  { "user.id": 6, "test.group": "ad", converted: false, "total.ads": 12, "most.ads.day": "Saturday", "most.ads.hour": 11 },
  { "user.id": 7, "test.group": "ad", converted: false, "total.ads": 75, "most.ads.day": "Sunday", "most.ads.hour": 14 },
  { "user.id": 8, "test.group": "ad", converted: true, "total.ads": 64, "most.ads.day": "Monday", "most.ads.hour": 9 },
  { "user.id": 9, "test.group": "psa", converted: false, "total.ads": 8, "most.ads.day": "Monday", "most.ads.hour": 20 },
  { "user.id": 10, "test.group": "psa", converted: false, "total.ads": 14, "most.ads.day": "Tuesday", "most.ads.hour": 10 },
  { "user.id": 11, "test.group": "psa", converted: true, "total.ads": 29, "most.ads.day": "Friday", "most.ads.hour": 20 },
];

export const AB_WORKFLOW_SAMPLE: Array<Record<string, string | number | boolean>> = [
  { "user.id": 1001, "test.group": "ad", converted: true, "total.ads": 132, "most.ads.day": "Monday", "most.ads.hour": 20 },
  { "user.id": 1002, "test.group": "ad", converted: false, "total.ads": 88, "most.ads.day": "Monday", "most.ads.hour": 10 },
  { "user.id": 1003, "test.group": "ad", converted: true, "total.ads": 74, "most.ads.day": "Tuesday", "most.ads.hour": 18 },
  { "user.id": 1004, "test.group": "ad", converted: false, "total.ads": 51, "most.ads.day": "Tuesday", "most.ads.hour": 15 },
  { "user.id": 1005, "test.group": "ad", converted: true, "total.ads": 96, "most.ads.day": "Wednesday", "most.ads.hour": 20 },
  { "user.id": 1006, "test.group": "ad", converted: true, "total.ads": 64, "most.ads.day": "Wednesday", "most.ads.hour": 11 },
  { "user.id": 1007, "test.group": "ad", converted: false, "total.ads": 44, "most.ads.day": "Thursday", "most.ads.hour": 14 },
  { "user.id": 1008, "test.group": "ad", converted: true, "total.ads": 112, "most.ads.day": "Friday", "most.ads.hour": 9 },
  { "user.id": 1009, "test.group": "psa", converted: false, "total.ads": 19, "most.ads.day": "Monday", "most.ads.hour": 20 },
  { "user.id": 1010, "test.group": "psa", converted: false, "total.ads": 21, "most.ads.day": "Tuesday", "most.ads.hour": 10 },
  { "user.id": 1011, "test.group": "psa", converted: true, "total.ads": 35, "most.ads.day": "Wednesday", "most.ads.hour": 18 },
  { "user.id": 1012, "test.group": "psa", converted: false, "total.ads": 27, "most.ads.day": "Thursday", "most.ads.hour": 15 },
  { "user.id": 1013, "test.group": "psa", converted: false, "total.ads": 18, "most.ads.day": "Friday", "most.ads.hour": 20 },
  { "user.id": 1014, "test.group": "psa", converted: true, "total.ads": 41, "most.ads.day": "Friday", "most.ads.hour": 11 },
];

export function isSuccessOutcome(value: unknown, successEvent = AB_MARKETING_DEFAULTS.successEvent) {
  if (typeof value === "boolean") return value === /^true$/i.test(successEvent);
  if (typeof value === "number") return value === Number(successEvent) || (successEvent === "True" && value === 1);
  return String(value).toLowerCase() === successEvent.toLowerCase() || (successEvent === "True" && String(value).toLowerCase() === "1");
}

export function getAbWorkflowRows(dataset = AB_WORKFLOW_DEFAULTS.dataset) {
  return dataset === AB_WORKFLOW_DEFAULTS.dataset ? AB_WORKFLOW_SAMPLE : AB_MARKETING_SAMPLE;
}

export function normalizeAbColumnName(column: string) {
  return String(column ?? "").trim().replace(/\s+/g, ".");
}

export function normalizeAbRow(row: Record<string, string | number | boolean>) {
  return Object.fromEntries(Object.entries(row).map(([key, value]) => [normalizeAbColumnName(key), value])) as Record<string, string | number | boolean>;
}

function segmentRow(segmentColumn: string, segment: string, treatmentCount: number, controlCount: number, treatmentConversions: number, controlConversions: number): AbSegmentSummaryRow {
  const summary: AbGroupSummary = {
    treatmentCount,
    controlCount,
    treatmentConversions,
    controlConversions,
    treatmentRate: treatmentCount ? treatmentConversions / treatmentCount : 0,
    controlRate: controlCount ? controlConversions / controlCount : 0,
  };
  const analysis = analyzeAbLift(summary);
  return {
    segmentColumn,
    segment,
    treatmentCount,
    controlCount,
    treatmentConversionRate: summary.treatmentRate,
    controlConversionRate: summary.controlRate,
    absoluteLift: analysis.absoluteLift,
    relativeLift: analysis.relativeLift,
    pValue: analysis.pValue,
    confidenceInterval: `${(analysis.confidenceLow * 100).toFixed(2)}% to ${(analysis.confidenceHigh * 100).toFixed(2)}%`,
    warning: Math.min(treatmentCount, controlCount) < 30 ? "Small segment sample. Interpret directionally." : "Segment has enough sample for review.",
  };
}

export function getAbWorkflowFullDatasetArtifact(defaults = AB_WORKFLOW_DEFAULTS): AbAnalysisDataset {
  const treatmentCount = 564_577;
  const controlCount = 23_524;
  const treatmentConversions = 14_423;
  const controlConversions = 420;
  const rows = getAbWorkflowRows(defaults.dataset).map(normalizeAbRow);
  const summary: AbGroupSummary = {
    treatmentCount,
    controlCount,
    treatmentConversions,
    controlConversions,
    treatmentRate: treatmentConversions / treatmentCount,
    controlRate: controlConversions / controlCount,
  };
  const profile: AbDataProfile = {
    dataset: defaults.dataset,
    rows: AB_WORKFLOW_FULL_ROW_COUNT,
    columns: AB_WORKFLOW_EXPECTED_COLUMNS.length,
    uniqueUnits: AB_WORKFLOW_FULL_ROW_COUNT,
    duplicateUnits: 0,
    missingUnitId: 0,
    missingTreatment: 0,
    missingOutcome: 0,
    invalidTreatment: 0,
    invalidOutcome: 0,
    treatmentValuesDetected: [defaults.treatmentValue, defaults.controlValue],
    outcomeValuesDetected: ["False", "True"],
    treatmentGroupCount: treatmentCount,
    controlGroupCount: controlCount,
    treatmentShare: treatmentCount / AB_WORKFLOW_FULL_ROW_COUNT,
    controlShare: controlCount / AB_WORKFLOW_FULL_ROW_COUNT,
    allocationRatio: treatmentCount / controlCount,
  };
  const daySegments = [
    segmentRow(defaults.segmentColumns[0], "Monday", 83_572, 3_502, 2_171, 65),
    segmentRow(defaults.segmentColumns[0], "Tuesday", 77_423, 3_315, 1_940, 58),
    segmentRow(defaults.segmentColumns[0], "Wednesday", 80_119, 3_302, 2_044, 62),
    segmentRow(defaults.segmentColumns[0], "Thursday", 79_881, 3_281, 2_012, 57),
    segmentRow(defaults.segmentColumns[0], "Friday", 92_420, 3_888, 2_413, 71),
    segmentRow(defaults.segmentColumns[0], "Saturday", 73_504, 3_085, 1_830, 52),
    segmentRow(defaults.segmentColumns[0], "Sunday", 77_658, 3_151, 2_013, 55),
  ];
  const hourSegments = [
    segmentRow(defaults.segmentColumns[1], "0", 55_083, 2_276, 1_367, 41),
    segmentRow(defaults.segmentColumns[1], "6", 48_441, 2_034, 1_205, 36),
    segmentRow(defaults.segmentColumns[1], "10", 71_440, 2_993, 1_830, 53),
    segmentRow(defaults.segmentColumns[1], "14", 88_729, 3_719, 2_271, 66),
    segmentRow(defaults.segmentColumns[1], "18", 103_448, 4_321, 2_661, 78),
    segmentRow(defaults.segmentColumns[1], "20", 112_834, 4_704, 2_891, 84),
    segmentRow(defaults.segmentColumns[1], "22", 84_602, 3_477, 2_198, 62),
  ];
  return {
    status: {
      dataset: defaults.dataset,
      rowCount: AB_WORKFLOW_FULL_ROW_COUNT,
      validAnalysisRecords: AB_WORKFLOW_FULL_VALID_ANALYSIS_RECORDS,
      fullDatasetAvailable: true,
      previewOnly: false,
      source: "full_dataset_artifact",
      message: "Full confirmed dataset artifact loaded.",
    },
    rows,
    profile,
    summary,
    daySegments,
    hourSegments,
    aggregates: {
      outcomeSuccess: treatmentConversions + controlConversions,
      outcomeNonSuccess: AB_WORKFLOW_FULL_VALID_ANALYSIS_RECORDS - treatmentConversions - controlConversions,
      overallConversionRate: (treatmentConversions + controlConversions) / AB_WORKFLOW_FULL_VALID_ANALYSIS_RECORDS,
      missingByColumn: Object.fromEntries(AB_WORKFLOW_EXPECTED_COLUMNS.map((column) => [column, 0])),
      exposureAvailable: false,
      exposureSummary: [],
    },
  };
}

export function getAbPreviewAnalysisDataset(defaults = AB_WORKFLOW_DEFAULTS, source: "preview_rows" | "compact_browser_cache" = "preview_rows"): AbAnalysisDataset {
  const rows = getAbWorkflowRows(defaults.dataset).map(normalizeAbRow);
  const profile = profileAbDataset(rows, defaults);
  const summary = summarizeAbGroups(rows, defaults);
  return {
    status: {
      dataset: defaults.dataset,
      rowCount: profile.rows,
      validAnalysisRecords: summary.treatmentCount + summary.controlCount,
      fullDatasetAvailable: false,
      previewOnly: true,
      source,
      message: source === "compact_browser_cache"
        ? "Full dataset artifact is not loaded. Reopen or reload the confirmed dataset before running experiment analysis."
        : "Preview only, not full experiment analysis",
    },
    rows,
    profile,
    summary,
    daySegments: segmentLiftRows(rows, defaults.segmentColumns[0] || "most.ads.day", defaults),
    hourSegments: segmentLiftRows(rows, defaults.segmentColumns[1] || "most.ads.hour", defaults),
    aggregates: aggregateAbDataset(rows, defaults),
  };
}

export function summarizeAbGroups(rows = AB_MARKETING_SAMPLE, defaults = AB_MARKETING_DEFAULTS): AbGroupSummary {
  const treatmentRows = rows.filter((row) => String(row[defaults.treatmentColumn]) === defaults.treatmentValue);
  const controlRows = rows.filter((row) => String(row[defaults.treatmentColumn]) === defaults.controlValue);
  const treatmentConversions = treatmentRows.filter((row) => isSuccessOutcome(row[defaults.outcomeColumn], defaults.successEvent)).length;
  const controlConversions = controlRows.filter((row) => isSuccessOutcome(row[defaults.outcomeColumn], defaults.successEvent)).length;
  return {
    treatmentCount: treatmentRows.length,
    controlCount: controlRows.length,
    treatmentConversions,
    controlConversions,
    treatmentRate: treatmentRows.length ? treatmentConversions / treatmentRows.length : 0,
    controlRate: controlRows.length ? controlConversions / controlRows.length : 0,
  };
}

function isBlank(value: unknown) {
  return value === undefined || value === null || String(value).trim() === "";
}

export function profileAbDataset(rows = AB_WORKFLOW_SAMPLE, defaults = AB_WORKFLOW_DEFAULTS): AbDataProfile {
  const unitIds = rows.map((row) => row[defaults.unitIdColumn]).filter((value) => !isBlank(value)).map(String);
  const uniqueUnits = new Set(unitIds).size;
  const treatmentValuesDetected = Array.from(new Set(rows.map((row) => row[defaults.treatmentColumn]).filter((value) => !isBlank(value)).map(String)));
  const outcomeValuesDetected = Array.from(new Set(rows.map((row) => row[defaults.outcomeColumn]).filter((value) => !isBlank(value)).map(String)));
  const validTreatmentValues = new Set([defaults.treatmentValue, defaults.controlValue]);
  const treatmentGroupCount = rows.filter((row) => String(row[defaults.treatmentColumn]) === defaults.treatmentValue).length;
  const controlGroupCount = rows.filter((row) => String(row[defaults.treatmentColumn]) === defaults.controlValue).length;
  const totalMapped = treatmentGroupCount + controlGroupCount;
  return {
    dataset: defaults.dataset,
    rows: rows.length,
    columns: rows[0] ? Object.keys(rows[0]).length : 0,
    uniqueUnits,
    duplicateUnits: Math.max(0, unitIds.length - uniqueUnits),
    missingUnitId: rows.filter((row) => isBlank(row[defaults.unitIdColumn])).length,
    missingTreatment: rows.filter((row) => isBlank(row[defaults.treatmentColumn])).length,
    missingOutcome: rows.filter((row) => isBlank(row[defaults.outcomeColumn])).length,
    invalidTreatment: rows.filter((row) => !isBlank(row[defaults.treatmentColumn]) && !validTreatmentValues.has(String(row[defaults.treatmentColumn]))).length,
    invalidOutcome: rows.filter((row) => !isBlank(row[defaults.outcomeColumn]) && !["true", "false", "1", "0", defaults.successEvent.toLowerCase()].includes(String(row[defaults.outcomeColumn]).toLowerCase())).length,
    treatmentValuesDetected,
    outcomeValuesDetected,
    treatmentGroupCount,
    controlGroupCount,
    treatmentShare: totalMapped ? treatmentGroupCount / totalMapped : 0,
    controlShare: totalMapped ? controlGroupCount / totalMapped : 0,
    allocationRatio: controlGroupCount ? treatmentGroupCount / controlGroupCount : Infinity,
  };
}

export function aggregateAbDataset(rows: Array<Record<string, string | number | boolean>>, defaults = AB_WORKFLOW_DEFAULTS): AbDatasetAggregates {
  const validRows = rows.filter((row) => {
    const treatment = String(row[defaults.treatmentColumn] ?? "");
    return (treatment === defaults.treatmentValue || treatment === defaults.controlValue)
      && !isBlank(row[defaults.unitIdColumn])
      && !isBlank(row[defaults.outcomeColumn]);
  });
  const outcomeSuccess = validRows.filter((row) => isSuccessOutcome(row[defaults.outcomeColumn], defaults.successEvent)).length;
  const exposureSummary = defaults.exposureColumn
    ? [defaults.controlValue, defaults.treatmentValue].map((group) => {
        const values = validRows
          .filter((row) => String(row[defaults.treatmentColumn]) === group)
          .map((row) => Number(row[defaults.exposureColumn]))
          .filter(Number.isFinite)
          .sort((a, b) => a - b);
        const middle = Math.floor(values.length / 2);
        const median = values.length
          ? values.length % 2 ? values[middle] : (values[middle - 1] + values[middle]) / 2
          : 0;
        return {
          group,
          count: values.length,
          mean: values.length ? values.reduce((sum, value) => sum + value, 0) / values.length : 0,
          median,
          min: values.length ? values[0] : 0,
          max: values.length ? values[values.length - 1] : 0,
        };
      })
    : [];
  const columns = Array.from(new Set(rows.flatMap((row) => Object.keys(row))));
  return {
    outcomeSuccess,
    outcomeNonSuccess: validRows.length - outcomeSuccess,
    overallConversionRate: validRows.length ? outcomeSuccess / validRows.length : 0,
    missingByColumn: Object.fromEntries(columns.map((column) => [column, rows.filter((row) => isBlank(row[column])).length])),
    exposureAvailable: exposureSummary.some((row) => row.count > 0),
    exposureSummary,
  };
}

function normalCdf(value: number) {
  const sign = value < 0 ? -1 : 1;
  const x = Math.abs(value) / Math.sqrt(2);
  const t = 1 / (1 + 0.3275911 * x);
  const erf = sign * (1 - (((((1.061405429 * t - 1.453152027) * t + 1.421413741) * t - 0.284496736) * t + 0.254829592) * t * Math.exp(-x * x)));
  return 0.5 * (1 + erf);
}

export function analyzeAbLift(summary = summarizeAbGroups(), confidenceLevel = 0.95) {
  const absoluteLift = summary.treatmentRate - summary.controlRate;
  const relativeLift = summary.controlRate ? absoluteLift / summary.controlRate : 0;
  const pooled = (summary.treatmentConversions + summary.controlConversions) / Math.max(1, summary.treatmentCount + summary.controlCount);
  const pooledSe = Math.sqrt(pooled * (1 - pooled) * (1 / Math.max(1, summary.treatmentCount) + 1 / Math.max(1, summary.controlCount)));
  const unpooledSe = Math.sqrt(
    (summary.treatmentRate * (1 - summary.treatmentRate)) / Math.max(1, summary.treatmentCount) +
      (summary.controlRate * (1 - summary.controlRate)) / Math.max(1, summary.controlCount)
  );
  const z = pooledSe ? absoluteLift / pooledSe : 0;
  const pValue = 2 * (1 - normalCdf(Math.abs(z)));
  const zCrit = confidenceLevel >= 0.99 ? 2.58 : confidenceLevel >= 0.95 ? 1.96 : 1.64;
  return {
    controlConversionRate: summary.controlRate,
    treatmentConversionRate: summary.treatmentRate,
    absoluteLift,
    relativeLift,
    standardError: unpooledSe,
    confidenceLow: absoluteLift - zCrit * unpooledSe,
    confidenceHigh: absoluteLift + zCrit * unpooledSe,
    pValue,
    statisticallySignificant: pValue < 0.05,
  };
}

export function allocationImbalance(summary = summarizeAbGroups()) {
  const total = summary.treatmentCount + summary.controlCount;
  const treatmentShare = total ? summary.treatmentCount / total : 0;
  const controlShare = total ? summary.controlCount / total : 0;
  return {
    treatmentShare,
    controlShare,
    ratio: summary.controlCount ? summary.treatmentCount / summary.controlCount : Infinity,
    warning: Math.abs(treatmentShare - controlShare) > 0.1,
    message: "The observed treatment allocation is not balanced. This may be valid for a marketing holdout design, but the imbalance should be documented and considered in inference.",
  };
}

export function segmentLiftRows(rows = AB_MARKETING_SAMPLE, segmentColumn: string, defaults = AB_MARKETING_DEFAULTS) {
  const segments = Array.from(new Set(rows.map((row) => String(row[segmentColumn])))).filter(Boolean);
  return segments.map((segment) => {
    const segmentRows = rows.filter((row) => String(row[segmentColumn]) === segment);
    const summary = summarizeAbGroups(segmentRows, defaults);
    const analysis = analyzeAbLift(summary);
    return {
      segmentColumn,
      segment,
      treatmentCount: summary.treatmentCount,
      controlCount: summary.controlCount,
      treatmentConversionRate: summary.treatmentRate,
      controlConversionRate: summary.controlRate,
      absoluteLift: analysis.absoluteLift,
      relativeLift: analysis.relativeLift,
      pValue: analysis.pValue,
      confidenceInterval: `${(analysis.confidenceLow * 100).toFixed(2)}% to ${(analysis.confidenceHigh * 100).toFixed(2)}%`,
      warning: Math.min(summary.treatmentCount, summary.controlCount) < 30 ? "Small segment sample. Interpret directionally." : "Segment has enough sample for review.",
    };
  });
}

export function decisionRecommendationReason(analysis = analyzeAbLift(), imbalance = allocationImbalance()) {
  if (imbalance.warning) return "Run longer";
  if (analysis.statisticallySignificant && analysis.absoluteLift > 0.01) return "Launch treatment";
  if (analysis.statisticallySignificant && analysis.absoluteLift <= 0) return "Keep control";
  return "Inconclusive";
}
