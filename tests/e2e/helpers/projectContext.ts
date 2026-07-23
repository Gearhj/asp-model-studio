import type { Page } from "@playwright/test";

export type ProjectContextNarrative = {
  businessObjective: string;
  intendedModelUse: string;
  targetDefinition: string;
  populationDefinition: string;
  observationWindow: string;
  performanceWindow: string;
};

export const CLASSIFICATION_NARRATIVE: ProjectContextNarrative = {
  businessObjective: "Reduce confirmed card-fraud losses by flagging high-risk transactions for review before settlement.",
  intendedModelUse: "A fraud analyst reviews the model's risk score alongside case history and decides whether to hold, decline, or release the transaction; the model output does not auto-decline.",
  targetDefinition: "Whether a given transaction was later confirmed as fraudulent by the card network's chargeback and dispute process.",
  populationDefinition: "All card-present and card-not-present transactions processed through the authorization system during the observation period.",
  observationWindow: "Transaction attributes available at authorization time, including amount and the anonymized behavioral PCA components captured by the fraud data platform.",
  performanceWindow: "Fraud confirmation outcome finalized within 120 days after the transaction date via chargeback or dispute resolution.",
};

export const REGRESSION_NARRATIVE: ProjectContextNarrative = {
  businessObjective: "Support appraisal review by estimating median home value for a census block group from public housing-census attributes.",
  intendedModelUse: "An appraisal analyst uses the estimated value as a reference point alongside comparable sales; the model output does not replace a licensed appraisal.",
  targetDefinition: "The median home value (in hundreds of thousands of dollars) for owner-occupied housing units in a census block group.",
  populationDefinition: "All California census block groups with complete housing and demographic attributes reported in the source housing census extract.",
  observationWindow: "Block-group housing and demographic attributes (income, age of housing stock, occupancy, location) available at the census extract date.",
  performanceWindow: "The median home value as reported in the same census extract; there is no separate outcome-maturation delay for this attribute.",
};

/**
 * Fills the six required Step00 "Project Context" narrative fields (LLMWritingAssist textareas).
 * These textareas sit inside a <label> that also wraps an AI-action <select> and an "Improve with
 * ATLAS AI" <button>; getByLabel() is ambiguous against that structure, so we target the textarea
 * directly by its distinct placeholder text instead.
 */
export async function fillProjectContextNarrative(page: Page, n: ProjectContextNarrative): Promise<void> {
  await page.getByPlaceholder("What decision or business process should this model improve, and what outcome should improve?").fill(n.businessObjective);
  await page.getByPlaceholder("Who will use the model output, what action may follow, and how will human judgment remain involved?").fill(n.intendedModelUse);
  await page.getByPlaceholder("What real-world outcome will the model predict? Define the outcome in business terms rather than naming a dataset column.").fill(n.targetDefinition);
  await page.getByPlaceholder("Which transactions, customers, accounts, applications, or other records are eligible for scoring?").fill(n.populationDefinition);
  await page.getByPlaceholder("The period and information available when the model would generate a score.").fill(n.observationWindow);
  await page.getByPlaceholder("The period after the observation date during which the final outcome is determined.").fill(n.performanceWindow);
}
