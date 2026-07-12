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

export const AB_MARKETING_EXPECTED_COLUMNS = [
  "user.id",
  "test.group",
  "converted",
  "total.ads",
  "most.ads.day",
  "most.ads.hour",
];

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

export function isSuccessOutcome(value: unknown, successEvent = AB_MARKETING_DEFAULTS.successEvent) {
  if (typeof value === "boolean") return value === /^true$/i.test(successEvent);
  if (typeof value === "number") return value === Number(successEvent) || (successEvent === "True" && value === 1);
  return String(value).toLowerCase() === successEvent.toLowerCase() || (successEvent === "True" && String(value).toLowerCase() === "1");
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
