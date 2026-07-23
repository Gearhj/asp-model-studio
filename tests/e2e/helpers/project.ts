import { expect, type Page } from "@playwright/test";

export type NewProjectOptions = { name: string; modelId: string };

/** Creates a new Predictive Modeling project through the real /projects/new UI and lands on /step00. */
export async function createPredictiveModelingProject(page: Page, opts: NewProjectOptions): Promise<void> {
  await page.goto("/projects/new");
  await page.getByRole("button", { name: "Predictive Modeling", exact: false }).first().click();

  const nameInput = page.getByLabel("Project name");
  await nameInput.fill("");
  await nameInput.fill(opts.name);

  const modelIdInput = page.getByLabel("Model ID #");
  await modelIdInput.fill(opts.modelId);

  const startButton = page.getByRole("button", { name: "Start Project" });
  await expect(startButton).toBeEnabled();
  await startButton.click();
  await expect(page).toHaveURL(/\/step00/, { timeout: 20_000 });
}
