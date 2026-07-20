import { loadLocalDataset } from "./localDataset";
import { loadProjectContext } from "./projectContext";
import { BRAND } from "../config/brand";
import { saveDecisionToDatabase } from "./serverPersistence";
import { useWorkflowStore } from "../state/useWorkflowStore";

export type DecisionActionType =
  | "project_context_updated"
  | "target_variable_selected"
  | "feature_inclusion_changed"
  | "outlier_method_selected"
  | "missing_value_strategy_selected"
  | "balancing_method_selected"
  | "split_strategy_selected"
  | "model_selected"
  | "hyperparameter_search_changed"
  | "champion_model_selected"
  | "evaluation_candidate_selected"
  | "evaluation_candidate_removed"
  | "challenge_response_recorded"
  | "final_model_saved"
  | "custom_python_code_edited"
  | "custom_sas_code_edited"
  | "workflow_setting_changed";

export type DecisionFollowStatus = "followed" | "overrode" | "not_applicable" | "unknown";

export type DecisionJournalEntry = {
  id: string;
  timestamp: string;
  workflowStep: string;
  actionType: DecisionActionType;
  subject: string;
  previousValue: string;
  newValue: string;
  systemRecommendation: string;
  followStatus: DecisionFollowStatus;
  userReason?: string;
};

export const DECISION_JOURNAL_KEY = "modeling-tool-decision-journal";
const MAX_LOCAL_DECISION_EVENTS = 150;
const MAX_DECISION_FIELD_CHARS = 750;

type LogDecisionInput = {
  workflowStep: string;
  actionType: DecisionActionType;
  subject: string;
  previousValue?: unknown;
  newValue?: unknown;
  systemRecommendation?: string;
  followStatus?: DecisionFollowStatus;
  userReason?: string;
  owner?: string;
};

function truncateText(value: string, maxChars = MAX_DECISION_FIELD_CHARS) {
  return value.length > maxChars ? `${value.slice(0, maxChars)}... [truncated]` : value;
}

function stringifyValue(value: unknown) {
  if (value === null || value === undefined || value === "") return "-";
  if (typeof value === "string") return truncateText(value);
  try {
    return truncateText(JSON.stringify(value));
  } catch {
    return truncateText(String(value));
  }
}

function safeReadEntries(): DecisionJournalEntry[] {
  try {
    const parsed = JSON.parse(localStorage.getItem(DECISION_JOURNAL_KEY) || "[]");
    return Array.isArray(parsed) ? parsed : [];
  } catch {
    return [];
  }
}

function compactEntry(entry: Partial<DecisionJournalEntry>): DecisionJournalEntry {
  return {
    id: String(entry.id || `${Date.now()}-${Math.random().toString(36).slice(2, 9)}`),
    timestamp: String(entry.timestamp || new Date().toISOString()),
    workflowStep: truncateText(String(entry.workflowStep || "Unknown"), 120),
    actionType: (entry.actionType || "workflow_setting_changed") as DecisionActionType,
    subject: truncateText(String(entry.subject || "-"), 180),
    previousValue: truncateText(String(entry.previousValue || "-")),
    newValue: truncateText(String(entry.newValue || "-")),
    systemRecommendation: truncateText(String(entry.systemRecommendation || "Review whether this decision is consistent with current Atlas Guide guidance.")),
    followStatus: (entry.followStatus || "unknown") as DecisionFollowStatus,
    userReason: truncateText(String(entry.userReason || "")),
  };
}

function persistDecisionEntries(entries: Partial<DecisionJournalEntry>[]) {
  const compacted = entries.map(compactEntry);
  const limits = [MAX_LOCAL_DECISION_EVENTS, 100, 50, 25, 10, 1];
  for (const limit of limits) {
    try {
      localStorage.setItem(DECISION_JOURNAL_KEY, JSON.stringify(compacted.slice(0, limit)));
      window.dispatchEvent(new CustomEvent("decision-journal-updated"));
      return true;
    } catch {
      // Try a smaller audit slice before giving up. Workflow navigation should not be blocked by audit-log storage pressure.
    }
  }
  return false;
}

function inferRecommendation(actionType: DecisionActionType, subject: string, newValue: unknown) {
  const projectContext = loadProjectContext();
  const dataset = loadLocalDataset();
  const value = String(newValue ?? "").toLowerCase();

  if (actionType === "target_variable_selected") {
    return "Choose the target that exactly matches the documented target definition and performance window.";
  }
  if (actionType === "feature_inclusion_changed") {
    return "Keep predictive, explainable features unless they introduce leakage, policy risk, proxy risk, or operational instability.";
  }
  if (actionType === "outlier_method_selected") {
    if (/amount|balance|income|payment|loan/i.test(subject)) {
      return "Review amount-like tail values before capping because the tail may contain material risk signal.";
    }
    return "Use conservative capping only when outliers are data-quality artifacts or operationally implausible.";
  }
  if (actionType === "missing_value_strategy_selected") {
    return "Prefer stable, explainable imputation: median for numeric variables, mode or explicit Missing category for categoricals, and document high-missingness exclusions.";
  }
  if (actionType === "balancing_method_selected") {
    return dataset?.problem_type === "regression"
      ? "Balancing is not applicable to regression targets."
      : "For rare-event classification, compare class weights, undersampling, or SMOTE using PR-AUC, recall, lift, and calibration.";
  }
  if (actionType === "split_strategy_selected") {
    return "Use a split strategy aligned to the model objective; use OOT validation where time drift or deployment stability matters.";
  }
  if (actionType === "model_selected") {
    return projectContext.interpretabilityRequirement === "high"
      ? "High-interpretability projects should include transparent models and document why any black-box challenger is justified."
      : "Train at least one interpretable model and one challenger model when governance allows it.";
  }
  if (actionType === "hyperparameter_search_changed") {
    return "Use grid search when challenger performance is material, but document the search space and avoid unreviewed complexity.";
  }
  if (actionType === "champion_model_selected") {
    return `Champion selection should prioritize ${projectContext.primarySuccessMetric || "the declared primary success metric"} while checking stability, interpretability, and operational fit.`;
  }
  if (actionType === "evaluation_candidate_selected") {
    return "Send only trained supervised candidates with relevant evaluation evidence to Interpretation for explainability review and final-model selection.";
  }
  if (actionType === "evaluation_candidate_removed") {
    return "Keep the Interpretation candidate set limited to models that remain relevant after evaluation review.";
  }
  if (actionType === "challenge_response_recorded") {
    return "Resolve Atlas Guide challenges by accepting the recommendation or documenting a defensible override rationale.";
  }
  if (actionType === "final_model_saved") {
    return "Save the final model only after RFE, diagnostics, stability, and governance rationale are reviewed.";
  }
  if (actionType === "custom_python_code_edited") {
    return "Custom code should be reproducible, documented, and aligned with the governed preprocessing and modeling pipeline.";
  }
  if (value) {
    return `Review whether ${value} is consistent with the project context and current Atlas Guide guidance.`;
  }
  return "Review whether this decision is consistent with the project context and current Atlas Guide guidance.";
}

function inferFollowStatus(actionType: DecisionActionType, subject: string, newValue: unknown): DecisionFollowStatus {
  const value = String(newValue ?? "").toLowerCase();
  const projectContext = loadProjectContext();
  if (!value) return "unknown";

  if (actionType === "outlier_method_selected" && /amount|balance|income|payment|loan/i.test(subject)) {
    return value.includes("none") ? "followed" : "overrode";
  }
  if (actionType === "missing_value_strategy_selected") {
    return /median|mode|constant|missing|none/i.test(value) ? "followed" : "unknown";
  }
  if (actionType === "model_selected" && projectContext.interpretabilityRequirement === "high") {
    return /logistic|decision|tree|ebm|logreg|dtree/i.test(value) ? "followed" : "unknown";
  }
  if (actionType === "hyperparameter_search_changed") {
    return value === "true" || value === "enabled" ? "followed" : "unknown";
  }
  return "unknown";
}

export function logDecision(input: LogDecisionInput) {
  if (typeof localStorage === "undefined") return null;
  const previousValue = stringifyValue(input.previousValue);
  const newValue = stringifyValue(input.newValue);
  if (previousValue === newValue) return null;

  const entry: DecisionJournalEntry = {
    id: `${Date.now()}-${Math.random().toString(36).slice(2, 9)}`,
    timestamp: new Date().toISOString(),
    workflowStep: input.workflowStep,
    actionType: input.actionType,
    subject: input.subject,
    previousValue,
    newValue,
    systemRecommendation:
      input.systemRecommendation ?? inferRecommendation(input.actionType, input.subject, input.newValue),
    followStatus:
      input.followStatus ?? inferFollowStatus(input.actionType, input.subject, input.newValue),
    userReason: input.userReason ?? "",
  };
  const entries = safeReadEntries();
  persistDecisionEntries([entry, ...entries]);
  const projectId = useWorkflowStore.getState().projectId;
  void saveDecisionToDatabase(projectId, {
    decisionId: entry.id,
    decisionType: entry.actionType,
    title: entry.subject,
    summary: `${entry.previousValue} -> ${entry.newValue}`,
    status: entry.followStatus === "overrode" ? "needs_review" : "recorded",
    owner: input.owner,
    createdAt: entry.timestamp,
    updatedAt: entry.timestamp,
    payload: entry,
  });
  return entry;
}

export function loadDecisionJournal() {
  return safeReadEntries();
}

export function saveDecisionJournal(entries: DecisionJournalEntry[]) {
  persistDecisionEntries(entries);
}

const materialDecisionTypes = new Set<DecisionActionType>([
  "project_context_updated",
  "target_variable_selected",
  "feature_inclusion_changed",
  "outlier_method_selected",
  "missing_value_strategy_selected",
  "balancing_method_selected",
  "split_strategy_selected",
  "model_selected",
  "champion_model_selected",
  "evaluation_candidate_selected",
  "evaluation_candidate_removed",
  "challenge_response_recorded",
  "final_model_saved",
]);

export function isMaterialDecisionEntry(entry: DecisionJournalEntry) {
  if (!materialDecisionTypes.has(entry.actionType)) return false;
  const text = `${entry.subject} ${entry.previousValue} ${entry.newValue}`.toLowerCase();
  return !/hover|open panel|close panel|viewed|expanded|collapsed/.test(text);
}

export function materialDecisionSummary(entries: DecisionJournalEntry[], maxEntries = 25) {
  return entries
    .filter(isMaterialDecisionEntry)
    .slice(0, maxEntries);
}

export function exportDecisionJournalMarkdown(entries: DecisionJournalEntry[]) {
  return [
    `# ${BRAND.productName}`,
    "",
    `## ${BRAND.productSubtitle}`,
    "",
    "### Decision Journal Audit Trail",
    "",
    `Generated: ${new Date().toISOString()}`,
    "",
    "The decision journal is structured as an audit timeline. Each entry captures the workflow step, action, prior value, new value, Atlas Guide recommendation context, follow status, and rationale.",
    "",
    ...entries.map((entry) =>
      [
        `## ${entry.timestamp}`,
        "",
        `**${entry.workflowStep}**`,
        "",
        `Action: ${entry.actionType.replace(/_/g, " ")}`,
        `Subject: ${entry.subject || "-"}`,
        `Previous: ${entry.previousValue || "-"}`,
        `New: ${entry.newValue || "-"}`,
        `Recommendation: ${entry.systemRecommendation || "-"}`,
        `Follow status: ${entry.followStatus}`,
        `Rationale: ${entry.userReason || "No user rationale captured."}`,
        "",
      ].join("\n")
    ),
    "",
  ].join("\n");
}

export function exportDecisionJournalCsv(entries: DecisionJournalEntry[]) {
  const headers = [
    "product",
    "product_subtitle",
    "timestamp",
    "workflow_step",
    "action_type",
    "subject",
    "previous_value",
    "new_value",
    "system_recommendation",
    "follow_status",
    "user_reason",
  ];
  const escape = (value: unknown) => `"${String(value ?? "").replace(/"/g, '""')}"`;
  const rows = entries.map((entry) =>
    [
      BRAND.productName,
      BRAND.productSubtitle,
      entry.timestamp,
      entry.workflowStep,
      entry.actionType,
      entry.subject,
      entry.previousValue,
      entry.newValue,
      entry.systemRecommendation,
      entry.followStatus,
      entry.userReason ?? "",
    ]
      .map(escape)
      .join(",")
  );
  return [headers.join(","), ...rows].join("\n");
}
