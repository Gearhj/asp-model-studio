import { expect, type Page } from "@playwright/test";

/** Selects one lightweight candidate model card by its visible label and submits training. */
export async function trainLightweightModel(page: Page, modelLabel: string): Promise<void> {
  await page.getByText(modelLabel, { exact: true }).first().click();
  const trainButton = page.getByRole("button", { name: /Train Selected Models|Validate & Train Selected Models/ });
  await expect(trainButton).toBeEnabled({ timeout: 30_000 });
  await trainButton.click();
  // First click may only run preflight validation; if so, the label flips and a second click starts training.
  await page.waitForTimeout(1500);
  const stillNeedsTrain = page.getByRole("button", { name: "Train Selected Models" });
  if (await stillNeedsTrain.isVisible().catch(() => false)) {
    await stillNeedsTrain.click();
  }
}

/** Polls until the given model shows a terminal status (Complete/Failed/Cancelled/Interrupted). */
export async function waitForTrainingTerminal(page: Page, timeoutMs = 5 * 60_000): Promise<string> {
  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {
    for (const status of ["Complete", "Failed", "Cancelled", "Interrupted"]) {
      if (await page.getByText(status, { exact: true }).first().isVisible().catch(() => false)) {
        return status;
      }
    }
    await page.waitForTimeout(2000);
  }
  throw new Error(`Training did not reach a terminal status within ${timeoutMs}ms`);
}
