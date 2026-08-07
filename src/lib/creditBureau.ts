import { logDecision } from "./decisionJournal";
import { loadLocalDataset } from "./localDataset";
import { loadProjectContext } from "./projectContext";
import { BRAND } from "../config/brand";

export const BUREAU_TREATMENT_KEY = "modeling-tool-bureau-special-value-treatments";
export const BUREAU_METADATA_KEY = "modeling-tool-bureau-metadata";

export type BureauMetadataScope = {
  projectId: string;
  datasetId: string;
  datasetVersionId: string;
};

export function bureauMetadataStorageKey(scope?: BureauMetadataScope) {
  if (!scope) return BUREAU_METADATA_KEY;
  return [
    BUREAU_METADATA_KEY,
    scope.projectId,
    scope.datasetId,
    scope.datasetVersionId,
  ]
    .map((value) => encodeURIComponent(value))
    .join(":");
}

export type BureauTreatment =
  | "keep_as_is"
  | "convert_to_missing"
  | "impute_bureau_equivalent"
  | "impute_median"
  | "impute_mean"
  | "indicator_and_impute"
  | "group_special_values"
  | "woe_target_rate"
  | "exclude_variable";

export type BureauMetadataRow = {
  variableName: string;
  bureauSource?: string;
  attributeDescription?: string;
  validNumericRange?: string;
  specialValueDefinitions?: string;
  expectedDirectionality?: string;
  monotonicExpectation?: string;
  variableFamily?: string;
  regulatorySensitivity?: string;
  allowedForModeling?: string;
};

export type BureauSpecialValueDefinition = {
  value: number;
  label: string;
  group: string;
};

export type BureauSpecialValueProfile = {
  variableName: string;
  value: number;
  label: string;
  group: string;
  count: number;
  percent: number;
  eventRate: number | null;
  regularEventRate: number | null;
  regularMeanTarget: number | null;
  regularMedian: number | null;
  regularMean: number | null;
  recommendedTreatment: BureauTreatment;
  recommendationReason: string;
  warning?: string;
  metadata?: BureauMetadataRow;
};

export type BureauTreatmentDecision = {
  variableName: string;
  value: number;
  treatment: BureauTreatment;
  rationale: string;
  updatedAt: string;
};

export const treatmentLabels: Record<BureauTreatment, string> = {
  keep_as_is: "Keep special value as-is",
  convert_to_missing: "Convert to missing",
  impute_bureau_equivalent: "Impute to bureau-equivalent value",
  impute_median: "Impute to regular median",
  impute_mean: "Impute to regular mean",
  indicator_and_impute: "Create indicator and impute",
  group_special_values: "Group special values",
  woe_target_rate: "WOE / target-rate encode",
  exclude_variable: "Exclude variable",
};

export const defaultSpecialValueRegistry: BureauSpecialValueDefinition[] = [
  { value: -1, label: "No trade history", group: "thin_file" },
  { value: -2, label: "No recent activity", group: "no_activity" },
  { value: -3, label: "Inquiry not found", group: "no_hit" },
  { value: -4, label: "Consumer not on file", group: "no_hit" },
  { value: -5, label: "Too few accounts", group: "thin_file" },
  { value: -6, label: "Suppressed value", group: "suppressed" },
  { value: -7, label: "Bureau exception", group: "unavailable" },
  { value: -8, label: "Frozen / blocked / unavailable", group: "unavailable" },
  { value: -9, label: "Unknown or unscorable response", group: "unknown" },
  { value: 96, label: "Bureau-specific exception", group: "exception" },
  { value: 97, label: "Suppressed value", group: "suppressed" },
  { value: 98, label: "Unavailable", group: "unavailable" },
  { value: 99, label: "Unknown", group: "unknown" },
  { value: 996, label: "Bureau-specific exception", group: "exception" },
  { value: 997, label: "Suppressed value", group: "suppressed" },
  { value: 998, label: "Unavailable", group: "unavailable" },
  { value: 999, label: "Unknown", group: "unknown" },
  { value: 9996, label: "Bureau-specific exception", group: "exception" },
  { value: 9997, label: "Suppressed value", group: "suppressed" },
  { value: 9998, label: "Unavailable", group: "unavailable" },
  { value: 9999, label: "Unknown", group: "unknown" },
];

function readJson<T>(key: string, fallback: T): T {
  try {
    const parsed = JSON.parse(localStorage.getItem(key) || "");
    return parsed ?? fallback;
  } catch {
    return fallback;
  }
}

function toNumber(value: unknown) {
  const numeric = Number(value);
  return Number.isFinite(numeric) ? numeric : null;
}

function percentile(sorted: number[], p: number) {
  if (!sorted.length) return null;
  const index = (sorted.length - 1) * p;
  const low = Math.floor(index);
  const high = Math.ceil(index);
  const weight = index - low;
  return sorted[low] * (1 - weight) + sorted[high] * weight;
}

function mean(values: number[]) {
  return values.length ? values.reduce((sum, value) => sum + value, 0) / values.length : null;
}

function metadataByVariable(metadata: BureauMetadataRow[]) {
  return new Map(metadata.map((row) => [row.variableName.toLowerCase(), row]));
}

function specialDefinitionsForVariable(metadata?: BureauMetadataRow) {
  const definitions = new Map(defaultSpecialValueRegistry.map((item) => [item.value, item]));
  const raw = metadata?.specialValueDefinitions ?? "";
  if (!raw.trim()) return definitions;

  const parts = raw.split(/[;|]/).map((part) => part.trim()).filter(Boolean);
  for (const part of parts) {
    const match = part.match(/(-?\d+(?:\.\d+)?)/);
    if (!match) continue;
    const value = Number(match[1]);
    if (!Number.isFinite(value)) continue;
    const label = part
      .replace(match[1], "")
      .replace(/^[:=\-\s]+/, "")
      .trim();
    definitions.set(value, {
      value,
      label: label || "Metadata-defined special value",
      group: metadata?.variableFamily || "metadata_defined",
    });
  }
  return definitions;
}

function isLikelyBureauVariable(name: string, metadata?: BureauMetadataRow) {
  if (metadata) return true;
  return /bureau|fico|score|tradeline|trade|inq|inquir|delinq|util|revolv|mortgage|install|derog|public|bankrupt|thin|file|credit|acct|account|balance/i.test(
    name
  );
}

function profileRecommendation(input: {
  percent: number;
  count: number;
  group: string;
  variableName: string;
}) {
  const context = loadProjectContext();
  const regulated = context.regulatoryEnvironment.some((item) =>
    ["Fair Lending", "FCRA", "ECOA", "SR 11-7", "OCC", "internal governance"].includes(item)
  );
  let recommendedTreatment: BureauTreatment = "indicator_and_impute";
  let recommendationReason =
    "Special bureau values should generally be preserved through an indicator or explicit treatment rather than handled as ordinary missing values.";
  let warning = "";

  if (input.percent >= 0.3) {
    recommendedTreatment = "indicator_and_impute";
    warning = "Special values exceed 30% of records. Document before using this variable because it may proxy bureau availability or thin-file status.";
    recommendationReason =
      "Dominant special values can represent availability, thin-file, or no-hit behavior rather than ordinary numeric values.";
  } else if (input.count < 30 || input.percent < 0.01) {
    recommendedTreatment = "group_special_values";
    recommendationReason = "The special value is rare and may be unstable on its own; grouping with similar bureau codes is recommended.";
  } else if (["suppressed", "unavailable", "unknown", "exception"].includes(input.group)) {
    recommendedTreatment = "convert_to_missing";
    recommendationReason =
      "Unavailable or suppressed values often behave like controlled missingness and should be routed through documented missing-value handling.";
  }

  if (regulated) {
    warning = warning || "Regulated credit decisioning context detected. Treatment must be documented for governance, fair lending, and audit review.";
  }

  return { recommendedTreatment, recommendationReason, warning };
}

export function loadBureauMetadata(scope?: BureauMetadataScope) {
  return readJson<BureauMetadataRow[]>(bureauMetadataStorageKey(scope), []);
}

export function saveBureauMetadata(
  rows: BureauMetadataRow[],
  scope?: BureauMetadataScope,
) {
  localStorage.setItem(bureauMetadataStorageKey(scope), JSON.stringify(rows));
  window.dispatchEvent(
    new CustomEvent("bureau-metadata-updated", {
      detail: scope ?? null,
    }),
  );
}

export function loadBureauTreatmentDecisions() {
  return readJson<BureauTreatmentDecision[]>(BUREAU_TREATMENT_KEY, []);
}

export function saveBureauTreatmentDecision(
  profile: BureauSpecialValueProfile,
  treatment: BureauTreatment,
  rationale: string
) {
  const existing = loadBureauTreatmentDecisions();
  const nextDecision: BureauTreatmentDecision = {
    variableName: profile.variableName,
    value: profile.value,
    treatment,
    rationale,
    updatedAt: new Date().toISOString(),
  };
  const next = [
    nextDecision,
    ...existing.filter((row) => !(row.variableName === profile.variableName && row.value === profile.value)),
  ];
  localStorage.setItem(BUREAU_TREATMENT_KEY, JSON.stringify(next));
  window.dispatchEvent(new CustomEvent("bureau-treatment-updated"));

  logDecision({
    workflowStep: "Credit Bureau Data Review",
    actionType: "workflow_setting_changed",
    subject: `${profile.variableName} = ${profile.value}`,
    previousValue: profile.recommendedTreatment,
    newValue: treatment,
    systemRecommendation: [
      `${treatmentLabels[profile.recommendedTreatment]}: ${profile.recommendationReason}`,
      `Count: ${profile.count}`,
      `Percent: ${(profile.percent * 100).toFixed(2)}%`,
      "Target comparison: pending governed development-population evidence",
    ].join(" | "),
    followStatus: treatment === profile.recommendedTreatment ? "followed" : "overrode",
    userReason: rationale,
  });
  return next;
}

export function parseBureauMetadataCsv(text: string): BureauMetadataRow[] {
  const lines = text.split(/\r?\n/).filter((line) => line.trim());
  if (lines.length < 2) return [];
  const headers = lines[0].split(",").map((header) => header.trim().toLowerCase());
  const rows = lines.slice(1).map((line) => {
    const values = line.split(",").map((value) => value.trim());
    const get = (...names: string[]) => {
      const index = headers.findIndex((header) => names.includes(header));
      return index >= 0 ? values[index] ?? "" : "";
    };
    return {
      variableName: get("variable name", "variable", "name", "field"),
      bureauSource: get("bureau source", "source", "bureau"),
      attributeDescription: get("attribute description", "description"),
      validNumericRange: get("valid numeric range", "range"),
      specialValueDefinitions: get("special value definitions", "special values", "special_value_definitions"),
      expectedDirectionality: get("expected directionality", "directionality"),
      monotonicExpectation: get("monotonic expectation", "monotonic"),
      variableFamily: get("variable family", "family"),
      regulatorySensitivity: get("regulatory sensitivity", "sensitivity"),
      allowedForModeling: get("allowed for modeling", "allowed"),
    } satisfies BureauMetadataRow;
  });
  return rows.filter((row) => row.variableName);
}

export function detectBureauSpecialValues() {
  const dataset = loadLocalDataset();
  if (!dataset?.rows.length) return [];
  const metadata = loadBureauMetadata();
  const metadataMap = metadataByVariable(metadata);
  const target = dataset.target;
  const profiles: BureauSpecialValueProfile[] = [];

  for (const variableName of dataset.headers.filter((header) => header !== target)) {
    const meta = metadataMap.get(variableName.toLowerCase());
    const definitions = specialDefinitionsForVariable(meta);
    const values = dataset.rows.map((row) => toNumber(row[variableName]));
    const numericValues = values.filter((value): value is number => value !== null);
    if (!numericValues.length || !isLikelyBureauVariable(variableName, meta)) continue;

    const specialValues = Array.from(new Set(numericValues.filter((value) => definitions.has(value)))).sort((a, b) => a - b);
    if (!specialValues.length) continue;
    const regularValues = numericValues.filter((value) => !definitions.has(value)).sort((a, b) => a - b);
    const regularMedian = percentile(regularValues, 0.5);
    const regularMean = mean(regularValues);

    for (const value of specialValues) {
      const definition = definitions.get(value)!;
      const rowsForValue = dataset.rows.filter((row) => toNumber(row[variableName]) === value);
      const count = rowsForValue.length;
      const percent = count / Math.max(1, dataset.rows.length);
      const recommendation = profileRecommendation({
        percent,
        count,
        group: definition.group,
        variableName,
      });
      profiles.push({
        variableName,
        value,
        label: definition.label,
        group: definition.group,
        count,
        percent,
        eventRate: null,
        regularEventRate: null,
        regularMeanTarget: null,
        regularMedian,
        regularMean,
        metadata: meta,
        ...recommendation,
      });
    }
  }

  return profiles.sort((a, b) => b.percent - a.percent || a.variableName.localeCompare(b.variableName));
}

export function summarizeBureauHandling() {
  const profiles = detectBureauSpecialValues();
  const decisions = loadBureauTreatmentDecisions();
  const decisionMap = new Map(decisions.map((row) => [`${row.variableName}::${row.value}`, row]));
  const variables = new Set(profiles.map((profile) => profile.variableName));
  const documented = profiles.filter((profile) => decisionMap.has(`${profile.variableName}::${profile.value}`)).length;
  return {
    variablesDetected: variables.size,
    specialValuesDetected: profiles.length,
    documentedDecisions: documented,
    profiles,
    decisions,
  };
}

export function generateBureauPythonCode() {
  const profiles = detectBureauSpecialValues();
  const decisions = loadBureauTreatmentDecisions();
  const decisionMap = new Map(decisions.map((row) => [`${row.variableName}::${row.value}`, row]));
  const treatmentRows = profiles.map((profile) => {
    const decision = decisionMap.get(`${profile.variableName}::${profile.value}`);
    return {
      variable: profile.variableName,
      value: profile.value,
      label: profile.label,
      group: profile.group,
      treatment: decision?.treatment ?? profile.recommendedTreatment,
      regular_median: profile.regularMedian,
      regular_mean: profile.regularMean,
      rationale: decision?.rationale ?? profile.recommendationReason,
    };
  });

  return `# Credit bureau special value handling
# Generated by ${BRAND.productName} - ${BRAND.productSubtitle}.

BUREAU_SPECIAL_VALUE_TREATMENTS = ${JSON.stringify(treatmentRows, null, 2)}

import numpy as np
import pandas as pd

def profile_bureau_special_values(df, target=None):
    if target is not None:
        raise RuntimeError(
            "Target-aware bureau comparisons require backend-verified exact development membership; "
            "this generated browser helper is structural-only."
        )
    rows = []
    for rule in BUREAU_SPECIAL_VALUE_TREATMENTS:
        variable = rule["variable"]
        value = rule["value"]
        if variable not in df.columns:
            continue
        mask = df[variable] == value
        row = {
            "variable": variable,
            "special_value": value,
            "count": int(mask.sum()),
            "percent": float(mask.mean()),
            "treatment": rule["treatment"],
            "rationale": rule["rationale"],
        }
        rows.append(row)
    return pd.DataFrame(rows)

def apply_bureau_special_value_treatments(df):
    df = df.copy()
    documentation = []
    for rule in BUREAU_SPECIAL_VALUE_TREATMENTS:
        variable = rule["variable"]
        value = rule["value"]
        treatment = rule["treatment"]
        if variable not in df.columns:
            continue
        mask = df[variable] == value
        flag_name = f"{variable}__special_{str(value).replace('-', 'neg')}"
        if treatment == "keep_as_is":
            pass
        elif treatment == "convert_to_missing":
            df.loc[mask, variable] = np.nan
        elif treatment == "impute_bureau_equivalent":
            df.loc[mask, variable] = rule.get("regular_median")
        elif treatment == "impute_median":
            df.loc[mask, variable] = rule.get("regular_median")
        elif treatment == "impute_mean":
            df.loc[mask, variable] = rule.get("regular_mean")
        elif treatment == "indicator_and_impute":
            df[flag_name] = mask.astype(int)
            df.loc[mask, variable] = rule.get("regular_median")
        elif treatment == "group_special_values":
            df[f"{variable}__special_group"] = np.where(mask, rule.get("group", "special"), "regular")
            df.loc[mask, variable] = rule.get("regular_median")
        elif treatment == "woe_target_rate":
            df[flag_name] = mask.astype(int)
            df.loc[mask, variable] = rule.get("regular_median")
        elif treatment == "exclude_variable":
            df = df.drop(columns=[variable])
        documentation.append(rule)
    return df, pd.DataFrame(documentation)
`;
}
