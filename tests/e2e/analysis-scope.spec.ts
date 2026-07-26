import path from "node:path";
import { fileURLToPath } from "node:url";
import { test, expect, type Page } from "@playwright/test";
import { makeTestUser, registerUser } from "./helpers/auth";
import { createPredictiveModelingProject } from "./helpers/project";
import { fillProjectContextNarrative, CLASSIFICATION_NARRATIVE } from "./helpers/projectContext";
import { goNext } from "./helpers/workflow";
import { attachDiagnostics } from "./helpers/diagnostics";
import { shot } from "./helpers/screenshots";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const FIRST_DATASET = "e2e_audit_classification_dev.csv";
// A materially different file, so replacing the workspace dataset genuinely
// changes the fingerprint the draft findings are pinned to.
const REPLACEMENT_DATASET = "class_train_fixture.csv";

async function openTargetTab(page: Page) {
  await page.getByRole("tab", { name: "Target" }).click();
  await expect(page.getByTestId("target-intelligence-workspace")).toBeVisible({ timeout: 60_000 });
}

test.describe("EDA Governed Analysis Scope and Evidence Integrity", () => {
  test("workspace draft cannot become governed evidence; registration produces a governed, version-pinned analysis", async ({ page }, testInfo) => {
    test.setTimeout(12 * 60_000);
    const { log, dump } = attachDiagnostics(page, testInfo);

    // ---------- 1-3. Sign in, project, unregistered upload -----------------
    const user = makeTestUser("scope");
    await registerUser(page, user);
    await createPredictiveModelingProject(page, {
      name: "E2E Governed Analysis Scope",
      modelId: `scope-${Date.now()}`,
    });
    await fillProjectContextNarrative(page, CLASSIFICATION_NARRATIVE);
    await goNext(page, /\/step01/);

    await page.locator('input[type="file"]').first().setInputFiles(path.join(__dirname, "data", FIRST_DATASET));
    await expect(page.locator("body")).toContainText("Class", { timeout: 60_000 });
    // Deliberately NOT registered yet.
    await goNext(page, /\/step02/);

    // ---------- 4-7. Draft scope is explicit and invents no version --------
    await openTargetTab(page);
    const banner = page.getByTestId("analysis-scope-banner");
    await expect(banner).toBeVisible();
    await expect(banner).toHaveAttribute("data-scope-mode", "workspace_draft");
    await expect(page.getByTestId("analysis-scope-label")).toHaveText("Workspace Draft Analysis");
    await expect(page.getByTestId("analysis-scope-disclosure")).toContainText("not tied to an immutable dataset version");
    await expect(page.getByTestId("analysis-scope-disclosure")).toContainText("not eligible for governed evidence");

    // 6 -- exactness is stated independently of governance.
    await expect(page.getByTestId("scope-exact")).toContainText("Exact");
    await expect(page.getByTestId("scope-population-rows")).not.toContainText("Not available");
    // 7 -- no version is invented.
    await expect(page.getByTestId("scope-version-id")).toContainText("Not version-pinned");
    await expect(page.getByTestId("scope-eligibility")).toContainText("Not eligible");
    await expect(page.getByTestId("scope-mdd")).toContainText("Not eligible");
    await shot(page, testInfo, "scope-01-workspace-draft");

    // ---------- 8-9. Evidence is disabled, with a visible reason -----------
    const saveEvidence = page.getByTestId("target-save-evidence");
    await expect(saveEvidence).toBeDisabled();
    const disabledReason = page.getByTestId("target-evidence-disabled-reason");
    await expect(disabledReason).toBeVisible();
    await expect(disabledReason).toContainText("Workspace Draft Analysis");
    await expect(disabledReason).toContainText("Register or link");
    await expect(page.getByTestId("target-evidence-register-cta")).toBeVisible();
    await shot(page, testInfo, "scope-02-evidence-disabled");

    // ---------- 10. Add a draft finding ------------------------------------
    const draftTitle = `Draft observation ${Date.now()}`;
    await expect(page.getByTestId("target-finding-scope-note")).toContainText("NOT stored against an immutable dataset version");
    await page.getByTestId("target-finding-title").fill(draftTitle);
    await page.getByTestId("target-finding-detail").fill("Prevalence looks extreme on the unregistered upload.");
    await page.getByTestId("target-finding-save").click();
    const draftFinding = page.getByTestId("target-finding-item").filter({ hasText: draftTitle }).first();
    await expect(draftFinding).toBeVisible({ timeout: 30_000 });
    await expect(draftFinding.getByTestId("target-finding-scope-label")).toHaveText("Draft Finding");
    await expect(draftFinding.getByTestId("target-finding-identity")).toContainText("not version-pinned");
    await shot(page, testInfo, "scope-03-draft-finding");

    // ---------- 11. Refresh: the draft finding persists for this dataset ----
    await page.reload();
    await page.waitForLoadState("networkidle");
    await openTargetTab(page);
    await expect(page.getByText(draftTitle)).toBeVisible({ timeout: 60_000 });
    await expect(page.getByTestId("analysis-scope-banner")).toHaveAttribute("data-scope-mode", "workspace_draft");

    // ---------- 12-13. Replace the workspace dataset -----------------------
    await page.goto("/step01");
    await page.waitForLoadState("networkidle");
    await page.locator('input[type="file"]').first().setInputFiles(path.join(__dirname, "data", REPLACEMENT_DATASET));
    await expect(page.locator("body")).toContainText("Class", { timeout: 60_000 });
    await page.goto("/step02");
    await page.waitForLoadState("networkidle");
    await openTargetTab(page);
    await expect(page.getByTestId("analysis-scope-banner")).toHaveAttribute("data-scope-mode", "workspace_draft");
    // The prior upload's draft finding must NOT be shown against the new dataset.
    await expect(page.getByText(draftTitle)).toHaveCount(0);
    await expect(page.getByTestId("target-findings-empty")).toBeVisible({ timeout: 30_000 });

    // ---------- 14. Register the dataset through Data Acquisition ----------
    await page.goto("/step01");
    await page.waitForLoadState("networkidle");
    // Registration is an explicit choice on Data Acquisition -- the governed
    // option must be selected before the registration form appears.
    await page
      .locator("button[aria-pressed]")
      .filter({ hasText: "Register in Dataset Library" })
      .first()
      .click();
    await page.getByRole("textbox", { name: "Dataset Library name" }).fill(`Scope Governed Asset ${Date.now()}`);
    const registerButton = page.getByTestId("register-dataset-action");
    await registerButton.scrollIntoViewIfNeeded();
    await expect(registerButton).toBeEnabled({ timeout: 30_000 });
    await registerButton.click();
    // After registration the page switches to the durable "already registered"
    // panel, which is the state that matters here -- the transient success card
    // is not the assertion target.
    await expect(page.locator("body")).toContainText("Registered in Dataset Library", { timeout: 90_000 });
    await expect(page.locator("body")).toContainText("Linked to this project", { timeout: 30_000 });

    // ---------- 15-18. Governed scope only after the registered run ---------
    await page.goto("/step02");
    await page.waitForLoadState("networkidle");
    await openTargetTab(page);

    // 16 -- the page must not instantly relabel the previous result as governed:
    // the banner is either still draft or explicitly "Resolving", never green
    // over a draft result.
    const resolutionBefore = await page.getByTestId("analysis-scope-banner").getAttribute("data-scope-resolution");
    console.log("SCOPE_RESOLUTION_ON_ARRIVAL:", resolutionBefore);
    expect(["workspace_draft", "draft", "resolving"]).toContain(String(resolutionBefore));

    // 17-18 -- the registered-version analysis completes and the scope turns governed.
    await expect(page.getByTestId("analysis-scope-banner")).toHaveAttribute("data-scope-mode", "governed_version", {
      timeout: 90_000,
    });
    await expect(page.getByTestId("analysis-scope-label")).toHaveText("Governed Dataset Version");
    const datasetId = (await page.getByTestId("scope-dataset-id").innerText()).split("\n").pop()?.trim() ?? "";
    const versionId = (await page.getByTestId("scope-version-id").innerText()).split("\n").pop()?.trim() ?? "";
    console.log("GOVERNED_SCOPE_IDENTITY:", JSON.stringify({ datasetId, versionId }));
    expect(datasetId).toMatch(/^ds/);
    expect(versionId).toMatch(/^v/);
    await expect(page.getByTestId("scope-immutable")).toContainText("Immutable");
    await expect(page.getByTestId("scope-eligibility")).toContainText("Evidence eligible");
    await shot(page, testInfo, "scope-04-governed-version");
    await shot(page, testInfo, "scope-06-version-identity-visible");

    // ---------- 19-20. Save governed evidence ------------------------------
    await expect(page.getByTestId("target-evidence-disabled-reason")).toHaveCount(0);
    const governedSave = page.getByTestId("target-save-evidence");
    await expect(governedSave).toBeEnabled();
    await governedSave.click();
    const savedBanner = page.getByTestId("target-evidence-saved");
    await expect(savedBanner).toBeVisible({ timeout: 60_000 });
    const evidenceText = await savedBanner.innerText();
    console.log("GOVERNED_EVIDENCE:", evidenceText);
    expect(evidenceText).toMatch(/ev-target-intel-/);
    await shot(page, testInfo, "scope-05-governed-evidence-saved");

    // ---------- 21-22. Refresh: governed scope persists ---------------------
    await page.reload();
    await page.waitForLoadState("networkidle");
    await openTargetTab(page);
    await expect(page.getByTestId("analysis-scope-banner")).toHaveAttribute("data-scope-mode", "governed_version", {
      timeout: 90_000,
    });
    await expect(page.getByTestId("scope-version-id")).toContainText(versionId);

    const governedTitle = `Governed observation ${Date.now()}`;
    await page.getByTestId("target-finding-title").fill(governedTitle);
    await page.getByTestId("target-finding-save").click();
    const governedFinding = page.getByTestId("target-finding-item").filter({ hasText: governedTitle }).first();
    await expect(governedFinding).toBeVisible({ timeout: 30_000 });
    await expect(governedFinding.getByTestId("target-finding-scope-label")).toHaveText("Governed Finding");
    await expect(governedFinding.getByTestId("target-finding-identity")).toContainText(versionId);

    // ---------- 23. A crafted draft-evidence request is refused -------------
    const crafted = await page.evaluate(async () => {
      const base = "http://127.0.0.1:8001/api";
      // Resolve a real project id so each crafted attempt is rejected for the
      // GOVERNANCE reason under test, not for a missing field.
      const projects = await (await fetch(`${base}/projects`, { credentials: "include" })).json();
      const pid = String((projects.projects ?? [])[0]?.projectId ?? "");
      const attempt = async (body: Record<string, unknown>) => {
        const response = await fetch(`${base}/analytics/target-evidence`, {
          method: "POST",
          credentials: "include",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(body),
        });
        return { status: response.status, detail: (await response.json().catch(() => ({}))).detail };
      };
      return {
        projectId: pid,
        // A draft analysis claiming governance.
        draftClaim: await attempt({
          projectId: pid, datasetId: "", versionId: "", target: "Class",
          analysisScope: { mode: "governed_version", evidenceEligible: true },
          evidenceEligible: true, mddEligible: true,
        }),
        // A fabricated version id.
        fakeVersion: await attempt({
          projectId: pid, datasetId: "ds_not_real", versionId: "v_fabricated", target: "Class",
        }),
      };
    });
    console.log("CRAFTED_EVIDENCE_ATTEMPTS:", JSON.stringify(crafted));
    expect([400, 403, 404, 409, 422]).toContain(crafted.draftClaim.status);
    expect([400, 403, 404, 409, 422]).toContain(crafted.fakeVersion.status);
    expect(crafted.draftClaim.status).not.toBe(200);
    expect(crafted.fakeVersion.status).not.toBe(200);

    // ---------- 24. No page errors caused by this phase ---------------------
    // A 4xx on these endpoints is the governance gate DOING its job (the crafted
    // attempts above are deliberately refused). Only a 5xx is a defect.
    const PHASE_ENDPOINTS = /\/api\/(analytics\/target-(assessment|by-predictor|findings|evidence|summary-export)|eda\/(target-by-predictor|workspace\/target))/;
    const phaseFailures = log.failedResponses.filter(
      (entry) => PHASE_ENDPOINTS.test(entry) && /^5\d\d /.test(entry)
    );
    console.log("SCOPE_PHASE_FAILURES:", JSON.stringify(phaseFailures));
    console.log("SCOPE_ALL_FAILED_RESPONSES:", JSON.stringify(log.failedResponses));
    expect(phaseFailures, `Scope endpoints failed unexpectedly: ${phaseFailures.join(" | ")}`).toEqual([]);
    expect(log.pageErrors, `Uncaught page errors: ${log.pageErrors.join(" | ")}`).toEqual([]);

    await dump();
  });

  test("event-majority fixture: a majority positive class is not described as a rare event", async ({ page }, testInfo) => {
    test.setTimeout(8 * 60_000);
    const { dump } = attachDiagnostics(page, testInfo);

    const user = makeTestUser("majority");
    await registerUser(page, user);
    await createPredictiveModelingProject(page, {
      name: "E2E Event Majority Semantics",
      modelId: `majority-${Date.now()}`,
    });
    await fillProjectContextNarrative(page, CLASSIFICATION_NARRATIVE);
    await goNext(page, /\/step01/);

    // Load a target whose configured event is the MAJORITY class directly into
    // the workspace, so the semantics can be exercised without a fixture file.
    const projectId = await page.evaluate(async () => {
      const base = "http://127.0.0.1:8001/api";
      const projects = await (await fetch(`${base}/projects`, { credentials: "include" })).json();
      const project = (projects.projects ?? [])[0];
      const rows = Array.from({ length: 1000 }, (_, index) => ({
        score: index % 97,
        outcome: index % 50 === 0 ? 0 : 1, // 98% are the configured event
      }));
      await fetch(`${base}/data/set_sample`, {
        method: "POST",
        credentials: "include",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          project_id: project.projectId,
          headers: ["score", "outcome"],
          rows,
          target: "outcome",
          selected_columns: ["score"],
        }),
      });
      return project.projectId as string;
    });
    console.log("MAJORITY_EVENT_PROJECT:", projectId);

    await page.goto("/step02");
    await page.waitForLoadState("networkidle");
    await openTargetTab(page);

    await expect(page.getByTestId("target-prevalence-label")).toContainText("Common event", { timeout: 60_000 });
    await expect(page.getByTestId("target-imbalance-label")).toContainText("imbalance");
    await expect(page.getByTestId("target-event-is-majority")).toBeVisible();
    await expect(page.getByTestId("target-event-is-majority")).toContainText("majority");
    // The critical assertion: no rare-event claim for a 98% event.
    await expect(page.getByTestId("target-prevalence-label")).not.toContainText("rare", { ignoreCase: true });
    await expect(page.getByTestId("target-ratio-orientation")).toContainText("non-events per event");
    await shot(page, testInfo, "scope-07-event-majority-semantics");

    await dump();
  });
});
