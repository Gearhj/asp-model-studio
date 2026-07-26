import { expect, type Page } from "@playwright/test";

export type NewProjectOptions = { name: string; modelId: string };

/** Creates a new Predictive Modeling project through the real /projects/new UI and lands on /step00. */
export async function createPredictiveModelingProject(page: Page, opts: NewProjectOptions): Promise<void> {
  await page.goto("/projects/new");
  // UX-NEWPROJECT-001 (structural correction): the unified setup section's "Create
  // Predictive Modeling Project" submit button now appears earlier in DOM order
  // than the workflow-selection cards, and its accessible name also contains
  // "Predictive Modeling" -- scope by aria-pressed (workflow cards only) to avoid
  // matching the (disabled, at this point) submit button instead.
  await page.locator("button[aria-pressed]").filter({ hasText: "Predictive Modeling" }).first().click();

  // Predictive Modeling's field label is "Model Name" (renamed from "Project name")
  // and its primary button reads "Create Predictive Modeling Project" (renamed
  // from "Start Project") -- both PM-specific per the New Project page UX fix.
  // The underlying projectName field/state is unchanged internally.
  const nameInput = page.getByLabel("Model Name", { exact: false });
  await nameInput.fill("");
  await nameInput.fill(opts.name);

  const modelIdInput = page.getByLabel("Model ID #", { exact: false });
  await modelIdInput.fill(opts.modelId);

  const startButton = page.getByRole("button", { name: "Create Predictive Modeling Project" });
  await expect(startButton).toBeEnabled();
  await startButton.click();
  await expect(page).toHaveURL(/\/step00/, { timeout: 20_000 });
}
