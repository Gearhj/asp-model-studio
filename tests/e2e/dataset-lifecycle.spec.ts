import path from "node:path";
import { fileURLToPath } from "node:url";
import { test, expect } from "@playwright/test";
import { makeTestUser, registerUser } from "./helpers/auth";
import { createPredictiveModelingProject } from "./helpers/project";
import { fillProjectContextNarrative, CLASSIFICATION_NARRATIVE } from "./helpers/projectContext";
import { goNext } from "./helpers/workflow";
import { shot } from "./helpers/screenshots";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const DATA_FILE = "e2e_audit_classification_dev.csv"; // 4,000-row safe copy of CLASS_TRAIN.csv
const LIBRARY_NAME = "E2E CLASS TRAIN Registered Asset";

/**
 * ATLAS Data Asset Lifecycle audit, Phase 8: exercises the previously-missing
 * "register an already-uploaded project workspace dataset to the Dataset Library"
 * path end to end through the real UI -- default Workspace Only state, explicit
 * registration, Dataset Library display, and reuse by a second authorized project.
 * Deletion/link-cleanup semantics are exercised via the same HTTP endpoints in
 * tests/dataset_lifecycle_test.py (14/14 passing) rather than repeated here.
 */
test.describe("Dataset Lifecycle: CLASS_TRAIN workspace upload through Library registration", () => {
  test("upload stays workspace-only, registers to Library, second project reuses it", async ({ page, context, browser }) => {
    test.setTimeout(6 * 60_000);

    const user = makeTestUser("dsLifecycle");
    await registerUser(page, user);
    await createPredictiveModelingProject(page, { name: "E2E Dataset Lifecycle Classification", modelId: `dsLc-${Date.now()}` });
    await fillProjectContextNarrative(page, CLASSIFICATION_NARRATIVE);

    // Upload real CLASS_TRAIN data (safe copy) through the actual Data Acquisition UI.
    await goNext(page, /\/step01/);
    const fileInput = page.locator('input[type="file"]');
    await fileInput.setInputFiles(path.join(__dirname, "data", DATA_FILE));
    await page.waitForTimeout(4000);

    const targetSelect = page.getByLabel("Target Column");
    await targetSelect.selectOption("Class");
    await page.waitForTimeout(1500); // let the target-driven backend sync (persistDataset happens on Next; sync also fires via the feature-profile effect)
    await shot(page, test.info(), "01-workspace-uploaded");

    // Default persistence choice is Project Workspace Only, and status says so.
    const persistenceCard = page.getByTestId("dataset-persistence-card");
    await expect(persistenceCard).toBeVisible();
    await expect(persistenceCard.getByText("Workspace Upload", { exact: true })).toBeVisible();
    await expect(page.getByRole("button", { name: "Project Workspace Only" })).toHaveAttribute("aria-pressed", "true");

    // Confirm NOT yet in the Dataset Library.
    const libraryCheck1 = await page.request.get("http://127.0.0.1:8001/api/datasets");
    expect(libraryCheck1.ok()).toBe(true);
    const namesBefore = (await libraryCheck1.json()).datasets.map((d: { name: string }) => d.name);
    expect(namesBefore).not.toContain(LIBRARY_NAME);

    // Switch to Register in Dataset Library and register.
    await page.getByRole("button", { name: "Register in Dataset Library" }).click();
    await expect(page.getByRole("button", { name: "Register in Dataset Library" })).toHaveAttribute("aria-pressed", "true");
    await page.getByPlaceholder(/Development Dataset/).fill(LIBRARY_NAME);
    await page.waitForTimeout(1000); // duplicate-check debounce (500ms, fires on typing)
    await shot(page, test.info(), "02-register-form-filled");

    const [registerResponse] = await Promise.all([
      page.waitForResponse((r) => r.url().includes("/datasets/register-workspace"), { timeout: 30_000 }),
      page.getByRole("button", { name: "Register Development Dataset" }).click(),
    ]);
    expect(registerResponse.status()).toBe(200);
    const registerBody = await registerResponse.json();
    expect(registerBody.ok).toBe(true);
    const datasetId: string = registerBody.dataset.datasetId;
    const versionId: string = registerBody.dataset.latestVersion.versionId;
    expect(registerBody.dataset.name).toBe(LIBRARY_NAME);
    expect(registerBody.dataset.sourceInfo.target).toBe("Class");
    expect(registerBody.dataset.latestVersion.rowCount).toBe(4000);

    await expect(page.getByTestId("registration-success")).toBeVisible({ timeout: 10_000 });
    await expect(page.getByText(datasetId)).toBeVisible();
    await shot(page, test.info(), "03-registration-success");

    // Dataset Library page shows the asset with correct fields.
    await page.getByTestId("registration-success").getByRole("link", { name: "Open in Dataset Library" }).click();
    await expect(page).toHaveURL(new RegExp(`/datasets/${datasetId}`));
    await expect(page.getByText(LIBRARY_NAME).first()).toBeVisible();
    await expect(page.getByText("4,000").first()).toBeVisible();
    await shot(page, test.info(), "04-dataset-detail");

    // Versions and Linked Projects sections render real data.
    await expect(page.getByTestId("versions-panel").getByText(versionId)).toBeVisible();
    await expect(page.getByTestId("linked-projects-panel").getByText("development", { exact: false })).toBeVisible();

    // Second authorized project (same user) links the SAME asset via Existing Dataset.
    await createPredictiveModelingProject(page, { name: "E2E Dataset Lifecycle Second Project", modelId: `dsLc2-${Date.now()}` });
    await fillProjectContextNarrative(page, CLASSIFICATION_NARRATIVE);
    await goNext(page, /\/step01/);
    await page.getByRole("button", { name: "Existing Dataset", exact: false }).click();
    await page.waitForTimeout(1500);
    // The picker auto-selects the most recently registered asset by default; confirm it
    // is the correct one via the rendered "Library Dataset" stat (regular DOM text, unlike
    // a native <select>'s <option> text) rather than re-selecting an already-correct value.
    await expect(page.getByText(LIBRARY_NAME, { exact: true })).toBeVisible({ timeout: 15_000 });
    const [activateResponse] = await Promise.all([
      page.waitForResponse((r) => r.url().includes("/activate"), { timeout: 15_000 }),
      page.getByRole("button", { name: "Load Selected Version" }).click(),
    ]);
    expect(activateResponse.status()).toBe(200);
    await shot(page, test.info(), "05-second-project-existing-dataset");

    // Next persists the link (persistDataset's existing-dataset branch).
    const [linkResponse] = await Promise.all([
      page.waitForResponse((r) => r.url().includes(`/projects/`) && r.url().includes("/datasets/link"), { timeout: 15_000 }),
      goNext(page, /\/step02/),
    ]);
    expect(linkResponse.status()).toBe(200);

    // Backend confirms both projects are linked to the SAME asset (no duplication).
    const linksResponse = await page.request.get(`http://127.0.0.1:8001/api/datasets/${datasetId}`);
    const linkedProjects = (await linksResponse.json()).dataset.linkedProjects;
    expect(linkedProjects.length).toBeGreaterThanOrEqual(2);

    // Second browser context / different session cannot see this private asset (isolation).
    const strangerContext = await browser.newContext();
    const strangerPage = await strangerContext.newPage();
    const strangerUser = makeTestUser("dsLifecycleStranger");
    await registerUser(strangerPage, strangerUser);
    const strangerListing = await strangerPage.request.get("http://127.0.0.1:8001/api/datasets");
    const strangerNames = (await strangerListing.json()).datasets.map((d: { name: string }) => d.name);
    expect(strangerNames).not.toContain(LIBRARY_NAME);
    const strangerDirectFetch = await strangerPage.request.get(`http://127.0.0.1:8001/api/datasets/${datasetId}`);
    expect(strangerDirectFetch.status()).toBe(403);
    await strangerContext.close();
  });
});
