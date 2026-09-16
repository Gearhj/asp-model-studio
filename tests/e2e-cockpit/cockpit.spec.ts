// Phase 7D.4 Gate 16 (browser) — focused PA Modeling Cockpit acceptance against a real, isolated scratch stack.
// The Python orchestrator (tests/sports_cockpit_phase7d4_browser_test.py) starts the scratch backend + vite dev,
// provisions real isolated V2 scientific state, and passes this fixture. Scientific API responses are NEVER mocked.
import { test, expect, type Page } from "@playwright/test";
import fs from "node:fs";

type Fx = {
  baseURL: string;
  primary: { email: string; password: string };
  secondary: { email: string; password: string };
  validProjectId: string;
  unauthorizedProjectId: string;
  failedProjectId: string;
};
const fx: Fx = JSON.parse(fs.readFileSync(process.env.COCKPIT_FIXTURE as string, "utf-8"));

// Benign console noise that never indicates a real defect: favicon, source maps, ResizeObserver loop notices, and
// the app's expected pre-login auth-detection network logs (a 401/403 from the initial `me()` probe before the UI
// shows the login form). A genuine failed scientific request would surface as 404/422/500 and is still caught, as
// is any uncaught JS exception (pageerror).
const BENIGN = [/favicon/i, /source ?map/i, /ResizeObserver loop/i, /Download the React DevTools/i,
                /Failed to load resource: the server responded with a status of 40[13]/i];
function watchConsole(page: Page): string[] {
  const errors: string[] = [];
  page.on("console", (m) => { if (m.type() === "error" && !BENIGN.some((r) => r.test(m.text()))) errors.push(m.text()); });
  page.on("pageerror", (e) => { const s = String(e); if (!BENIGN.some((r) => r.test(s))) errors.push(s); });
  return errors;
}

async function login(page: Page, email: string, password: string) {
  await page.goto(`${fx.baseURL}/login`);
  await page.locator('input:not([type="checkbox"]):not([type="password"])').first().fill(email);
  await page.locator('input[type="password"]').first().fill(password);
  await page.getByRole("button", { name: "Sign In" }).click();
  await page.waitForURL(/\/dashboard/, { timeout: 45_000 });
}

async function openCockpit(page: Page, projectId: string) {
  await page.goto(`${fx.baseURL}/pa-modeling-cockpit?projectId=${encodeURIComponent(projectId)}`);
  await expect(page.getByRole("heading", { name: /MLB Plate-Appearance Model/i })).toBeVisible({ timeout: 45_000 });
}

// Navigate the cockpit's internal step navigator to a labelled step (the left-nav buttons call setActive()).
async function gotoStep(page: Page, label: string) {
  await page.getByRole("button", { name: new RegExp(`^\\d+`) }).first().waitFor({ timeout: 30_000 }).catch(() => {});
  await page.getByRole("button", { name: label, exact: false }).first().click();
}

async function assertNoUndefinedOrObject(page: Page) {
  const body = (await page.locator("body").innerText()).toLowerCase();
  expect(body).not.toContain("undefined");
  expect(body).not.toContain("[object object]");
}

// ---------------- Scenario 1 — verified project + candidate render the V2 evidence ----------------
test("verified project renders V2 active candidate, evaluation, calibration, registry", async ({ page }) => {
  const errors = watchConsole(page);
  await login(page, fx.primary.email, fx.primary.password);
  await openCockpit(page, fx.validProjectId);

  await gotoStep(page, "Evaluation");
  // Active Candidate card renders an immutable run id (32 hex), not undefined
  await expect(page.getByText(/Active candidate · server authority/i)).toBeVisible();
  await expect(page.getByText(/Run id/i).first()).toBeVisible({ timeout: 30_000 });
  // Evaluation shows the independent recompute + a log-loss value from the real V2 response
  await expect(page.getByText(/Independent log loss recomputed/i)).toBeVisible({ timeout: 30_000 });
  await expect(page.getByText(/2024 validation/i).first()).toBeVisible();
  await assertNoUndefinedOrObject(page);

  await gotoStep(page, "Calibration");
  await expect(page.getByText(/calibrator not configured/i)).toBeVisible({ timeout: 30_000 });
  await assertNoUndefinedOrObject(page);

  await gotoStep(page, "Champion / Challenger");
  await expect(page.getByText(/Active challenger/i)).toBeVisible({ timeout: 30_000 });
  await assertNoUndefinedOrObject(page);

  await gotoStep(page, "Registry, Export & Implementation");
  await expect(page.getByText(/Run evidence record/i)).toBeVisible({ timeout: 30_000 });
  await expect(page.getByText(/Evidence manifest/i).first()).toBeVisible();
  await assertNoUndefinedOrObject(page);

  expect(errors, `console errors: ${errors.join(" | ")}`).toEqual([]);
});

// ---------------- Scenario 2 — project identity preserved across refresh ----------------
test("project identity is preserved across a browser refresh", async ({ page }) => {
  await login(page, fx.primary.email, fx.primary.password);
  await openCockpit(page, fx.validProjectId);
  await gotoStep(page, "Evaluation");
  await expect(page.getByText(/Independent log loss recomputed/i)).toBeVisible({ timeout: 30_000 });
  await page.reload();
  expect(new URL(page.url()).searchParams.get("projectId")).toBe(fx.validProjectId);
  await gotoStep(page, "Evaluation");
  await expect(page.getByText(/Independent log loss recomputed/i)).toBeVisible({ timeout: 30_000 });
});

// ---------------- Scenario 3 — failed verification is explicit (not disguised as no-candidate) ----------------
test("a failed-verification project shows an explicit verification-failed state", async ({ page }) => {
  await login(page, fx.primary.email, fx.primary.password);
  await openCockpit(page, fx.failedProjectId);
  await gotoStep(page, "Evaluation");
  await expect(page.getByText(/verification failed or unavailable/i).first()).toBeVisible({ timeout: 30_000 });
  // it must NOT masquerade as a verified candidate
  await expect(page.getByText(/Independent log loss recomputed/i)).toHaveCount(0);
  await assertNoUndefinedOrObject(page);
});

// ---------------- Scenario 4 — unauthorized project is rejected honestly, no evidence leaked ----------------
test("an unauthorized project shows an explicit unauthorized state and leaks no evidence", async ({ page }) => {
  await login(page, fx.secondary.email, fx.secondary.password);
  await openCockpit(page, fx.unauthorizedProjectId);   // owned by the PRIMARY user
  await gotoStep(page, "Evaluation");
  await expect(page.getByText(/unauthorized|do not have access/i).first()).toBeVisible({ timeout: 30_000 });
  await expect(page.getByText(/Independent log loss recomputed/i)).toHaveCount(0);
  await assertNoUndefinedOrObject(page);
});
