import { test, expect, type Page } from "@playwright/test";
import { attachDiagnostics } from "./helpers/diagnostics";
import { shot } from "./helpers/screenshots";
import { makeTestUser, registerUser } from "./helpers/auth";

// UX-NEWPROJECT-001 (generalized): the unified, darker Project Setup section is
// now the SAME shared, schema-driven layout for every workflow type, not a
// Predictive-Modeling-only branch. This spec exercises the real page across
// several representative workflow types (see tests/newProjectUx.test.mjs for
// the fast, non-browser companion covering all 9 configured workflow types'
// copy/config).

type WorkflowCase = {
  cardLabel: string;
  requiredSummary: string;
  optionalSummary: string | null;
  nameLabel: string;
  modelIdVisible: boolean;
  modelIdRequired: boolean;
  buttonLabel: string;
  redirectsTo: RegExp;
};

const PREDICTIVE_MODELING: WorkflowCase = {
  cardLabel: "Predictive Modeling",
  requiredSummary: "Model Name and Model ID",
  optionalSummary: null,
  nameLabel: "Model Name",
  modelIdVisible: true,
  modelIdRequired: true,
  buttonLabel: "Create Predictive Modeling Project",
  redirectsTo: /\/step00/,
};

const OPTIMIZATION: WorkflowCase = {
  cardLabel: "Optimization",
  requiredSummary: "Project Name",
  optionalSummary: "Model ID",
  nameLabel: "Project Name",
  modelIdVisible: true,
  modelIdRequired: false,
  buttonLabel: "Create Optimization Project",
  redirectsTo: /\/project-overview/,
};

const EXPERIMENTATION: WorkflowCase = {
  cardLabel: "Experimentation",
  requiredSummary: "Project Name",
  optionalSummary: "Model ID",
  nameLabel: "Project Name",
  modelIdVisible: true,
  modelIdRequired: false,
  buttonLabel: "Create Experimentation Project",
  redirectsTo: /\/project-overview/,
};

const CUSTOM_WORKFLOW: WorkflowCase = {
  cardLabel: "Custom Workflow",
  requiredSummary: "Project Name",
  optionalSummary: null,
  nameLabel: "Project Name",
  modelIdVisible: false,
  modelIdRequired: false,
  buttonLabel: "Create Custom Workflow Project",
  redirectsTo: /\/project-overview/,
};

async function selectWorkflowCard(page: Page, cardLabel: string): Promise<void> {
  // Workflow-selection cards are the only buttons with aria-pressed -- scoping by
  // that attribute avoids ambiguity with the setup section's submit button, whose
  // accessible name may also contain the workflow's display name.
  await page.locator("button[aria-pressed]").filter({ hasText: cardLabel }).first().click();
}

function unifiedSection(page: Page) {
  return page.getByTestId("unified-setup-section");
}

async function verifyCaseStructure(page: Page, testCase: WorkflowCase): Promise<void> {
  const section = unifiedSection(page);
  const workflowLibrary = page.getByRole("heading", { name: "Choose Project Type" });
  await expect(section).toBeVisible();

  // Above the Workflow Library.
  const [sectionBox, libraryBox] = await Promise.all([section.boundingBox(), workflowLibrary.boundingBox()]);
  expect(sectionBox).not.toBeNull();
  expect(libraryBox).not.toBeNull();
  expect(sectionBox!.y).toBeLessThan(libraryBox!.y);

  // No duplicate / old right-column form. `aside` is not checked page-wide here --
  // the app shell's own persistent navigation chrome legitimately uses <aside>
  // elsewhere on every page; the precise, unambiguous proof that the OLD
  // right-column "Project Details" form (and its Predictive-Modeling-only
  // predecessor) is gone is that none of their old field ids exist anywhere.
  await expect(page.getByTestId("required-setup-panel")).toHaveCount(0);
  await expect(page.locator('#new-project-name, #new-project-model-id-optional, #new-project-model-name, #new-project-model-id')).toHaveCount(0);
  await expect(page.locator('[id="new-project-name-field"]')).toHaveCount(1);

  // Summary chips (targeted by stable data-testid -- "Optional"/label text alone is
  // ambiguous, since a field-level Required/Optional badge can carry the same text).
  await expect(page.getByTestId("setup-chip-Required Setup-value")).toHaveText(testCase.requiredSummary);
  if (testCase.optionalSummary) {
    await expect(page.getByTestId("setup-chip-Optional-value")).toHaveText(testCase.optionalSummary);
  } else {
    await expect(page.getByTestId("setup-chip-Optional")).toHaveCount(0);
  }

  // Field labels and required/optional semantics.
  const nameInput = section.getByLabel(testCase.nameLabel, { exact: false });
  await expect(nameInput).toBeVisible();
  await expect(nameInput).toHaveAttribute("aria-required", "true");
  await expect(nameInput).toHaveValue("");

  const modelIdInput = page.locator('[id="new-project-model-id-field"]');
  if (testCase.modelIdVisible) {
    await expect(modelIdInput).toHaveCount(1);
    await expect(modelIdInput).toHaveAttribute("aria-required", String(testCase.modelIdRequired));
    await expect(modelIdInput).toHaveValue("");
  } else {
    // No Model ID field at all for this workflow -- not shown-and-empty, genuinely absent.
    await expect(modelIdInput).toHaveCount(0);
  }

  // Button label (or approved "Create Project" fallback).
  await expect(section.getByRole("button", { name: testCase.buttonLabel })).toBeVisible();

  // No horizontal overflow.
  const hasHorizontalScroll = await page.evaluate(() => document.documentElement.scrollWidth > document.documentElement.clientWidth + 1);
  expect(hasHorizontalScroll).toBe(false);
}

test.describe("New Project page: unified setup section is shared across all workflow types", () => {
  for (const testCase of [PREDICTIVE_MODELING, OPTIMIZATION, EXPERIMENTATION, CUSTOM_WORKFLOW]) {
    test(`${testCase.cardLabel}: unified section, validation, and creation behave correctly`, async ({ page }, testInfo) => {
      test.setTimeout(2 * 60_000);
      const { dump } = attachDiagnostics(page, testInfo);
      await registerUser(page, makeTestUser(`newprojectux${testCase.cardLabel.replace(/[^a-z]/gi, "").toLowerCase()}`));

      await page.goto("/projects/new");
      await selectWorkflowCard(page, testCase.cardLabel);
      await verifyCaseStructure(page, testCase);

      const section = unifiedSection(page);
      const nameInput = section.getByLabel(testCase.nameLabel, { exact: false });
      const createButton = section.getByRole("button", { name: testCase.buttonLabel });
      const guidance = page.getByTestId("setup-guidance");

      // Disabled + honest guidance before any required field is filled -- Predictive
      // Modeling has TWO required fields (combined message), everything else has one.
      await expect(createButton).toBeDisabled();
      await expect(guidance).toHaveText(
        testCase.modelIdVisible && testCase.modelIdRequired
          ? "Enter both required fields to continue."
          : `Enter a ${testCase.nameLabel} to continue.`
      );

      // Whitespace-only must not satisfy the requirement.
      await nameInput.fill("   ");
      await expect(createButton).toBeDisabled();

      await nameInput.fill(`${testCase.cardLabel} Consistency Test`);

      if (testCase.modelIdVisible && testCase.modelIdRequired) {
        // Predictive Modeling: still blocked until Model ID is filled too.
        await expect(createButton).toBeDisabled();
        await expect(guidance).toHaveText("Enter a Model ID to continue.");
        await page.locator('[id="new-project-model-id-field"]').fill("15299");
        await expect(createButton).toBeEnabled();
        await expect(guidance).toHaveText("Ready to create the project.");
      } else if (testCase.modelIdVisible && !testCase.modelIdRequired) {
        // Optional Model ID left blank -- must not block, and guidance must say so
        // honestly ("is optional"), not imply readiness is contingent on it, and
        // not fall back to the generic "Ready" message while it's unaddressed.
        await expect(createButton).toBeEnabled();
        await expect(guidance).toHaveText("Model ID is optional.");
      } else {
        // No Model ID field at all (e.g. Custom Workflow) -- Name alone is enough.
        await expect(createButton).toBeEnabled();
        await expect(guidance).toHaveText("Ready to create the project.");
      }
      await shot(page, testInfo, `${testCase.cardLabel.replace(/[^a-z]/gi, "-").toLowerCase()}-ready-to-create`);

      // Diagnostics are captured and dumped for the record (see dump() below), but not
      // hard-asserted here: a direct diagnosis (see final report) confirmed the only
      // console/network noise on this page (401 on /api/auth/me, 404 on /api/train/last)
      // comes from pre-existing global app-shell chrome polling project context before
      // any project exists yet -- present regardless of this fix, not introduced by it.

      // Keyboard submission (Enter inside the last filled field) works, not just a click.
      await nameInput.focus();
      await page.keyboard.press("Enter");
      await expect(page).toHaveURL(testCase.redirectsTo, { timeout: 20_000 });

      await dump();
    });
  }

  test("Switching workflow types updates the shared setup section without stale values or labels", async ({ page }, testInfo) => {
    test.setTimeout(60_000);
    const { dump } = attachDiagnostics(page, testInfo);
    await registerUser(page, makeTestUser("newprojectuxswitch"));

    await page.goto("/projects/new");
    await selectWorkflowCard(page, "Predictive Modeling");
    const section = unifiedSection(page);
    await section.getByLabel("Model Name", { exact: false }).fill("Switch Test Model Name");
    await expect(section.getByRole("button", { name: "Create Predictive Modeling Project" })).toBeVisible();
    await expect(page.locator('[id="new-project-model-id-field"]')).toHaveCount(1);

    // Switch to a workflow with no Model ID field and a different required-field label.
    await selectWorkflowCard(page, "Custom Workflow");
    await expect(section.getByRole("button", { name: "Create Custom Workflow Project" })).toBeVisible();
    await expect(page.locator('[id="new-project-model-id-field"]')).toHaveCount(0);
    // The Name field must reset -- no stale "Switch Test Model Name" value carried over
    // under the new "Project Name" label.
    await expect(section.getByLabel("Project Name", { exact: false })).toHaveValue("");
    await expect(page.getByText("Model Name")).toHaveCount(0);

    await dump();
  });

  test("A long custom workflow name does not overflow or break the unified section", async ({ page }, testInfo) => {
    test.setTimeout(60_000);
    const { dump } = attachDiagnostics(page, testInfo);
    await registerUser(page, makeTestUser("newprojectuxlongname"));

    await page.goto("/projects/new");
    await selectWorkflowCard(page, "Custom Workflow");
    await page.getByLabel("Custom workflow name", { exact: false }).fill(
      "An Extremely Long Custom Workflow Name Used Specifically To Verify That The Unified Project Setup Section Wraps Gracefully Without Introducing Horizontal Overflow"
    );

    const section = unifiedSection(page);
    await expect(section).toBeVisible();
    const hasHorizontalScroll = await page.evaluate(() => document.documentElement.scrollWidth > document.documentElement.clientWidth + 1);
    expect(hasHorizontalScroll).toBe(false);
    await expect(section.getByRole("button", { name: "Create Custom Workflow Project" })).toBeVisible();

    await dump();
  });

  test("Unified setup section stays above the Workflow Library at a narrow viewport", async ({ page }, testInfo) => {
    test.setTimeout(60_000);
    const { dump } = attachDiagnostics(page, testInfo);
    await registerUser(page, makeTestUser("newprojectuxnarrow"));
    await page.setViewportSize({ width: 390, height: 844 });

    await page.goto("/projects/new");
    await selectWorkflowCard(page, "Predictive Modeling");
    await verifyCaseStructure(page, PREDICTIVE_MODELING);
    await shot(page, testInfo, "narrow-viewport");

    await dump();
  });
});
