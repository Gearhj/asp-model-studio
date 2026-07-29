import {
  expect,
  test,
  type Locator,
  type Page,
  type TestInfo,
} from "@playwright/test";

test.use({
  trace: "off",
  video: "off",
  viewport: { width: 1536, height: 864 },
});

async function requireAuthenticatedHelocEda(page: Page) {
  await page.goto("/step02");
  const loginHeading = page.getByRole("heading", {
    name: /Sign in to ATLAS/i,
  });
  const context = page.getByTestId("eda-governed-context-strip");
  await expect(loginHeading.or(context)).toBeVisible({ timeout: 60_000 });
  const loginVisible =
    /\/(?:login|sign-in)(?:[/?#]|$)/i.test(page.url()) ||
    (await loginHeading.isVisible().catch(() => false));
  if (loginVisible) {
    test.skip(
      true,
      "Final acceptance requires the user's already authenticated browser session; no seeded credentials are used.",
    );
  }

  await expect(context).toBeVisible({ timeout: 60_000 });
  await expect(context).toContainText(/HELOC_TRAIN/i);
  await expect(context).toContainText("bad_flag");
}

async function captureRegion(
  locator: Locator,
  testInfo: TestInfo,
  name: string,
) {
  await locator.scrollIntoViewIfNeeded();
  await expect(locator).toBeVisible();
  const path = testInfo.outputPath(`${name}.png`);
  await locator.screenshot({ path, animations: "disabled" });
  await testInfo.attach(name, { path, contentType: "image/png" });
}

async function captureViewport(
  page: Page,
  testInfo: TestInfo,
  name: string,
) {
  const path = testInfo.outputPath(`${name}.png`);
  await page.screenshot({ path, fullPage: false, animations: "disabled" });
  await testInfo.attach(name, { path, contentType: "image/png" });
}

test("authenticated HELOC_TRAIN / bad_flag final acceptance walkthrough", async ({
  page,
}, testInfo) => {
  test.setTimeout(10 * 60_000);

  const pageErrors: string[] = [];
  const consoleErrors: string[] = [];
  page.on("pageerror", (error) => pageErrors.push(error.message));
  page.on("console", (message) => {
    if (message.type() === "error") consoleErrors.push(message.text());
  });

  await requireAuthenticatedHelocEda(page);
  await expect(
    page.getByRole("heading", {
      name: "Step 2: Exploratory Data Analysis",
    }),
  ).toBeVisible();
  await expect(page.getByRole("tab")).toHaveCount(6);

  await captureRegion(
    page.getByTestId("eda-compact-preamble"),
    testInfo,
    "01-eda-page-header-and-tabs",
  );

  await page.getByRole("tab", { name: "Target", exact: true }).click();
  const targetWorkspace = page.getByTestId("target-intelligence-workspace");
  await expect(targetWorkspace).toBeVisible({ timeout: 90_000 });
  await page.evaluate(() => window.scrollTo({ top: 0, behavior: "instant" }));
  await captureViewport(page, testInfo, "02-target-above-the-fold");

  const balance = page.getByTestId("target-balance-confidence");
  await expect(balance).toHaveAttribute(
    "data-scope",
    "full-governed-population",
  );
  await expect(balance.getByTestId("target-balance-bar")).toBeVisible();
  await expect(
    balance.getByTestId("target-confidence-interval"),
  ).toBeVisible();
  await captureRegion(
    balance,
    testInfo,
    "03-target-balance-and-confidence",
  );

  const quality = page.getByTestId("target-quality-diagnostic");
  await expect(quality.locator("[data-quality-diagnostic]")).toHaveCount(6);
  await expect(
    quality.getByTestId("target-source-exclusion-diagnostic"),
  ).toContainText("RiskPerformance");
  await captureRegion(
    quality,
    testInfo,
    "04-target-quality-diagnostic",
  );

  const targetPreview = page.getByTestId(
    "target-event-rate-predictor-preview",
  );
  await expect(targetPreview).toBeVisible();
  await expect(
    targetPreview.getByTestId("target-predictor-preview-card").first(),
  ).toBeVisible();
  expect(
    await targetPreview.getByTestId("target-predictor-preview-card").count(),
  ).toBeLessThanOrEqual(5);
  await expect(targetPreview).not.toContainText("bad_flag");
  await expect(targetPreview).not.toContainText("RiskPerformance");
  await captureRegion(
    targetPreview,
    testInfo,
    "05-target-event-rate-preview",
  );

  await page.getByRole("tab", { name: "Predictors", exact: true }).click();
  const landscape = page.getByTestId("predictor-signal-landscape");
  await expect(landscape).toBeVisible({ timeout: 90_000 });
  const visibleLimit = page.getByTestId("predictor-visible-limit");
  const optionValues = await visibleLimit
    .locator("option")
    .evaluateAll((options) =>
      options.map((option) => (option as HTMLOptionElement).value),
    );
  expect(optionValues.length).toBeGreaterThan(0);
  expect(new Set(optionValues).size).toBe(optionValues.length);
  await expect(landscape).not.toContainText("bad_flag");
  await expect(landscape).not.toContainText("RiskPerformance");
  await captureRegion(
    landscape,
    testInfo,
    "06-predictor-dropdown-corrected",
  );

  await page
    .getByRole("tab", { name: "Stability & Segments", exact: true })
    .click();
  const stability = page.getByTestId("eda-stability-unavailable");
  await expect(stability).toBeVisible({ timeout: 90_000 });
  await expect(stability).toHaveAttribute("data-analysis-available", "false");
  await expect(stability).toHaveAttribute(
    "data-confirmation-impact",
    "non-blocking",
  );
  await expect(stability).toContainText("No analysis fabricated");
  await expect(stability).toContainText(
    "Population Stability Index (PSI)",
  );
  await captureRegion(
    stability,
    testInfo,
    "07-stability-empty-state",
  );

  await page.getByRole("tab", { name: "Findings", exact: true }).click();
  const findingsWorkspace = page.getByTestId(
    "eda-findings-decision-workspace",
  );
  await expect(findingsWorkspace).toBeVisible({ timeout: 90_000 });

  const executiveSummary = page.getByTestId(
    "eda-findings-executive-summary",
  );
  await captureRegion(
    executiveSummary,
    testInfo,
    "08-findings-executive-summary",
  );

  const inventory = page.getByTestId("eda-findings-inventory");
  await expect(inventory.locator("button[data-finding-id]").first()).toBeVisible();
  await captureRegion(
    inventory,
    testInfo,
    "09-findings-inventory",
  );

  const detail = page.getByTestId("eda-finding-detail");
  await expect(detail).toBeVisible();
  await captureRegion(detail, testInfo, "10-finding-detail");

  const transformations = page.getByTestId(
    "eda-suggested-transformations",
  );
  const suggestedFinding = transformations.locator("button").first();
  await expect(suggestedFinding).toBeVisible();
  await suggestedFinding.click();
  const transformation = page.getByTestId("eda-finding-transformation");
  const transformationValues = await transformation
    .locator("option")
    .evaluateAll((options) =>
      options.map((option) => (option as HTMLOptionElement).value),
    );
  const recommendedTransformation =
    transformationValues.find((value) => value !== "No transformation") ??
    transformationValues[0];
  expect(recommendedTransformation).toBeTruthy();
  await transformation.selectOption(recommendedTransformation);
  await captureRegion(
    transformations,
    testInfo,
    "11-suggested-transformations",
  );

  await page
    .getByTestId("eda-finding-disposition")
    .selectOption("accepted");
  await page
    .getByTestId("eda-finding-destination")
    .selectOption("Validation");
  await page
    .getByTestId("eda-finding-rationale")
    .fill(
      "Final acceptance walkthrough: carry forward for independent validation review.",
    );
  await expect(
    page.getByTestId("eda-finding-disposition"),
  ).toHaveValue("accepted");

  const carryForward = page.getByTestId("eda-carry-forward-queue");
  await expect(carryForward).toHaveAttribute(
    "data-carry-forward-mode",
    "draft_recommendation",
  );
  await expect(carryForward).toHaveAttribute(
    "data-mutation-applied",
    "false",
  );
  await expect(carryForward).toContainText("Validation");
  await captureRegion(
    carryForward,
    testInfo,
    "12-carry-forward-queue",
  );

  const commentary = page.getByLabel("Reviewer commentary");
  if (!(await commentary.inputValue()).trim()) {
    await commentary.fill(
      "Final EDA acceptance: governed findings reviewed for model-development carry-forward.",
    );
  }
  await page.getByLabel("EDA finding status").selectOption("accepted");
  await page
    .getByRole("button", { name: "Save to Evidence Center" })
    .click();
  await expect
    .poll(
      async () =>
        (await page.getByTestId("eda-documentation-message").textContent()) ??
        "",
      { timeout: 30_000 },
    )
    .toMatch(
      /Documentation draft is synchronized|Draft changes saved/,
    );

  await page.goto("/model-document-studio");
  const mddLink = page.getByTestId("eda-documentation-live-link");
  await expect(mddLink).toBeVisible({ timeout: 60_000 });
  const draft = page.locator(
    '[aria-labelledby="draft-eda-documentation-title"]',
  );
  await expect(draft).toContainText("Draft changes");
  await expect(draft).toContainText("Documentation impact");
  await expect(draft).not.toContainText(
    "No EDA documentation draft is available",
  );
  await captureRegion(
    mddLink,
    testInfo,
    "13-mdd-draft-impact",
  );

  expect(pageErrors, "uncaught page errors").toEqual([]);
  expect(consoleErrors, "browser console errors").toEqual([]);
});

test("reduced motion leaves final analytical visuals visible", async ({
  page,
}) => {
  const pageErrors: string[] = [];
  const consoleErrors: string[] = [];
  page.on("pageerror", (error) => pageErrors.push(error.message));
  page.on("console", (message) => {
    if (message.type() === "error") consoleErrors.push(message.text());
  });

  await page.emulateMedia({ reducedMotion: "reduce" });
  await requireAuthenticatedHelocEda(page);
  await page.getByRole("tab", { name: "Target", exact: true }).click();
  await expect(
    page.getByTestId("target-intelligence-workspace"),
  ).toHaveAttribute("data-reduced-motion", "true");
  await expect(page.getByTestId("target-balance-bar")).toBeVisible();

  await page.getByRole("tab", { name: "Predictors", exact: true }).click();
  await expect(
    page.locator("[data-landscape-mark]").first(),
  ).toBeVisible({ timeout: 90_000 });
  await expect(page.locator("[data-landscape-mark]").first()).toHaveAttribute(
    "r",
    /[1-9]/,
  );

  expect(pageErrors, "uncaught page errors").toEqual([]);
  expect(consoleErrors, "browser console errors").toEqual([]);
});
