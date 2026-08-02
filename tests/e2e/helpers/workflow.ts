import { expect, type Page } from "@playwright/test";

/** Generic selector for every workflow step's sticky-footer "Next" button (StepShell.tsx). */
export const NEXT_BUTTON = '[data-step-next-button="true"]';

export async function nextButtonLocator(page: Page) {
  return page.locator(NEXT_BUTTON);
}

/**
 * Some steps require an explicit "materialize" action (Apply treatments, Materialize full
 * dataset, ...) before their Next button will enable. Click any of these that are visible
 * and enabled before advancing -- harmless no-op on steps that don't have one.
 */
const GATING_ACTION_LABELS = [
  "Apply treatments",
  "Materialize full dataset",
  "Save manifest",
  // Balance & Split (step06): predictor gate must be (re)saved before a split can be created.
  "Restore Data Acquisition selection",
  "Save predictor selections",
  "Create Validation Split",
  "Rebuild Validation Split",
  // Interpretation (step09): the exact evaluated candidate must be saved before Scoring unlocks.
  // RFE is optional analysis and is deliberately not a progression gate.
  "Save as Final Model",
];

export async function clickGatingActionsIfPresent(page: Page): Promise<void> {
  // Two passes: some pages chain gates (e.g. Balance & Split's "Restore selection" ->
  // "Save predictor selections" -> "Create Validation Split" only enables after the save
  // request round-trips), so a single left-to-right pass can find a later button still disabled.
  for (let pass = 0; pass < 2; pass += 1) {
    for (const label of GATING_ACTION_LABELS) {
      const btn = page.getByRole("button", { name: label, exact: false }).first();
      if (await btn.isVisible().catch(() => false)) {
        if (await btn.isEnabled().catch(() => false)) {
          // Best-effort: these buttons can re-render mid-click as their own state updates
          // (e.g. "applying" -> "applied"); a lost race here just means the Next-button's
          // own disabled-state check still gates correctly, so we don't fail the whole flow.
          await btn.click({ timeout: 5000 }).catch(() => undefined);
          await page.waitForTimeout(2500);
        }
      }
    }
  }
}

/** Clicks the step's Next button (waiting for it to enable) and waits for the route to change. */
export async function goNext(page: Page, expectedUrlPattern?: RegExp): Promise<void> {
  const before = page.url();
  const button = page.locator(NEXT_BUTTON);
  const deadline = Date.now() + 90_000;
  await clickGatingActionsIfPresent(page);
  while (Date.now() < deadline) {
    if (await button.isEnabled().catch(() => false)) break;
    await clickGatingActionsIfPresent(page);
    await page.waitForTimeout(1000);
  }
  await expect(button).toBeEnabled({ timeout: 10_000 });
  await button.click();
  if (expectedUrlPattern) {
    await expect(page).toHaveURL(expectedUrlPattern, { timeout: 30_000 });
  } else {
    await page.waitForFunction((prev) => window.location.href !== prev, before, { timeout: 30_000 });
  }
  await page.waitForLoadState("networkidle").catch(() => undefined);
}

export async function isNextDisabled(page: Page): Promise<boolean> {
  return page.locator(NEXT_BUTTON).isDisabled();
}

export async function waitForStep(page: Page, step: number): Promise<void> {
  const padded = String(step).padStart(2, "0");
  await expect(page).toHaveURL(new RegExp(`/step${padded}(?:$|[/?])`), { timeout: 30_000 });
}
