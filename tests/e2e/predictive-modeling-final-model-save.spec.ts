import path from "node:path";
import { execFileSync } from "node:child_process";
import { fileURLToPath } from "node:url";
import { test, expect } from "@playwright/test";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const PYTHON = path.join(__dirname, "..", "..", ".venv", "Scripts", "python.exe");
const SEED_SCRIPT = path.join(__dirname, "helpers", "seedTrainedProject.py");

/**
 * Stage B.5 regression test: reproduces the confirmed defect (a stale
 * interpretationContextQuery in Step09_Interpretation.tsx caused "Save as Final Model" to
 * persist an outdated dataset_version/target, which Scoring's fresh re-derivation then
 * rejected as "belongs to a different project, dataset version, or target"). Uses API
 * seeding to reach a completed-training project quickly (per this stage's instructions),
 * then exercises the real UI for exact evaluation-package handoff, optional RFE analysis,
 * exact-candidate promotion, and Scoring readiness -- the actual code path that was broken.
 */
test("exact evaluated candidate -> Save as Final Model -> Scoring accepts the saved model", async ({ page, context }) => {
  test.setTimeout(8 * 60_000);

  const seedRaw = execFileSync(PYTHON, [SEED_SCRIPT, "E2E Final Model Save Fix"], { encoding: "utf-8", timeout: 300_000 });
  const seed = JSON.parse(seedRaw.trim().split("\n").pop() as string);
  expect(seed.training_status).toBe("complete");

  await context.addCookies([
    { name: "atlas_session", value: seed.cookies.atlas_session, domain: "127.0.0.1", path: "/", httpOnly: true, sameSite: "Lax" },
  ]);

  // Establish the frontend's active-project state directly (sessionStorage, zustand persist
  // key "ds-workflow-store") -- this is separate client-side state from the backend project
  // the API seeding created; see Stage B's report for why "Open Project" doesn't restore it
  // for an API-seeded project.
  await page.addInitScript(({ projectId, projectName }) => {
    const steps = ["step00", "step01", "step02", "step03", "step04", "step05", "step06", "step07", "step08", "step09", "step10", "step11", "step12", "step13"];
    const stepStatus = Object.fromEntries(steps.map((id) => [id, ["step08", "step09", "step10", "step11", "step12", "step13"].includes(id) ? "pending" : "complete"]));
    const workflowSteps = steps.map((id, index) => ({ id, label: id, route: `/${id}`, status: stepStatus[id] ?? "pending", order: index }));
    const wfState = {
      projectId, modelId: projectName, projectName, projectType: "predictive-modeling",
      workflowId: "predictive-modeling", workflowSteps, currentStepId: "step08", steps: stepStatus,
      restoreWarnings: [],
    };
    window.sessionStorage.setItem("ds-workflow-store", JSON.stringify({ state: wfState, version: 0 }));
  }, { projectId: seed.project_id, projectName: "E2E Final Model Save Fix" });

  await page.goto("/step08");
  await page.waitForLoadState("networkidle");
  await page.waitForTimeout(2000);
  await page.getByRole("button", { name: "Review Model" }).first().click();
  await page.getByTitle("Add to Comparison").first().click();
  const openInterpretation = page.getByRole("button", { name: "Open Interpretation" }).first();
  await expect(openInterpretation).toBeEnabled({ timeout: 60_000 });
  await openInterpretation.click();
  await expect(page).toHaveURL(/\/step09\?.*evaluation_package_id=/, { timeout: 30_000 });
  await page.waitForLoadState("networkidle");
  await page.waitForTimeout(2000);

  // RFE remains optional analysis. Exercise it here, but it cannot change the candidate
  // contract or evaluation package that the promotion request must preserve exactly.
  const runRfeBtn = page.getByRole("button", { name: /Run RFE|Rerun RFE/ });
  await expect(runRfeBtn).toBeEnabled({ timeout: 15_000 });
  await runRfeBtn.click();
  await expect(page.getByText(/Run RFE to rank candidate features\./)).toHaveCount(0, { timeout: 60_000 });
  await page.waitForTimeout(1000);

  // Save as Final Model, and capture the real request payload sent to the backend.
  const saveFinalBtn = page.getByRole("button", { name: "Save as Final Model" });
  await expect(saveFinalBtn).toBeEnabled({ timeout: 10_000 });
  const [saveResponse] = await Promise.all([
    page.waitForResponse((r) => r.url().includes("/model/save_final"), { timeout: 90_000 }),
    saveFinalBtn.click(),
  ]);
  const saveBody = await saveResponse.json().catch(() => null);
  expect(saveResponse.status()).toBe(200);
  expect(saveBody?.ok, JSON.stringify(saveBody)).toBe(true);

  // "Final Artifact" hero metric must flip to "Saved" -- proves finalModelReady actually became true.
  await expect(page.getByText("Saved", { exact: true }).first()).toBeVisible({ timeout: 10_000 });

  const [statusResponse] = await Promise.all([
    page.waitForResponse((r) => r.url().includes("/model/final/status"), { timeout: 30_000 }),
    page.goto("/step10"),
  ]);
  const statusBody = await statusResponse.json().catch(() => null);
  await page.waitForLoadState("networkidle");
  await page.waitForTimeout(1500);

  // The confirmed defect: Scoring rejecting the just-saved model as belonging to a different
  // project/dataset/target. Must not appear now that Interpretation always sends the current
  // (not stale) dataset_version/target (Stage B.5) AND Scoring no longer treats an absent
  // local expectation as a mismatch (Stage B.6, resolveFinalModelReadiness).
  expect(statusBody?.ready, JSON.stringify(statusBody)).toBe(true);
  await expect(page.getByText(/belongs to a different project, dataset version, or target/i)).toHaveCount(0);
  await expect(page.getByText("A verified final model is required", { exact: false })).toHaveCount(0);

  // Stage B.6: the ready state must actually render -- governed scoring contract visible
  // with the verified-artifact badge, and the development-split scoring control available.
  await expect(page.getByTestId("final-model-scoring-contract")).toBeVisible({ timeout: 15_000 });
  await expect(page.getByText("Verified artifact", { exact: true })).toBeVisible();
  await expect(page.getByRole("button", { name: "Score TRAIN" })).toBeEnabled();
});
