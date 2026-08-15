import { expect, test, type Page } from "@playwright/test";

const viewports = [
  { name: "1366x768", width: 1366, height: 768 },
  { name: "1536x864", width: 1536, height: 864 },
  { name: "1920x1080", width: 1920, height: 1080 },
] as const;

async function requireAuthenticatedEda(page: Page) {
  await page.goto("/step02");
  if (await page.getByRole("heading", { name: "Sign in to ATLAS" }).count()) {
    test.skip(
      true,
      "Final-polish acceptance requires the user's already authenticated browser state.",
    );
  }
  await expect(page.getByTestId("eda-governed-context-strip")).toBeVisible();
}

async function firstContentOffset(page: Page, analyticalTestId: string) {
  return page.evaluate((testId) => {
    const breadcrumb = document.querySelector(
      '[data-testid="atlas-breadcrumb"]',
    );
    const header = breadcrumb?.closest("header");
    const visual = document.querySelector(`[data-testid="${testId}"]`);
    if (!(header instanceof HTMLElement) || !(visual instanceof HTMLElement)) {
      return null;
    }
    return {
      offset: visual.getBoundingClientRect().top - header.getBoundingClientRect().bottom,
      visualTop: visual.getBoundingClientRect().top,
      viewportHeight: window.innerHeight,
    };
  }, analyticalTestId);
}

for (const viewport of viewports) {
  test(`compact EDA and predictor visual suite pass at ${viewport.name}`, async ({
    page,
  }) => {
    const runtimeErrors: string[] = [];
    const failedResponses: string[] = [];
    const predictorRequests: string[] = [];
    page.on("pageerror", (error) => runtimeErrors.push(error.message));
    page.on("console", (message) => {
      if (message.type() === "error") runtimeErrors.push(message.text());
    });
    page.on("request", (request) => {
      if (request.url().includes("/api/eda/workspace/predictors")) {
        predictorRequests.push(request.url());
      }
    });
    page.on("response", (response) => {
      if (response.status() >= 400) {
        failedResponses.push(`${response.status()} ${response.url()}`);
      }
    });

    await page.setViewportSize({
      width: viewport.width,
      height: viewport.height,
    });
    await requireAuthenticatedEda(page);

    await expect(page.getByTestId("eda-governed-context-strip")).toHaveCount(1);
    await expect(page.locator('[data-context-panel="governed"]')).toHaveCount(1);
    await expect(page.getByTestId("eda-governed-context-details")).not.toHaveAttribute(
      "open",
      "",
    );
    await expect(page.getByTestId("eda-compact-preamble")).toHaveAttribute(
      "data-preamble-budget-status",
      "within-budget",
    );

    const overviewOffset = await firstContentOffset(page, "eda-dataset-fingerprint");
    expect(overviewOffset).not.toBeNull();
    expect(overviewOffset!.visualTop).toBeLessThan(overviewOffset!.viewportHeight);
    if (viewport.name === "1536x864") {
      expect(overviewOffset!.offset).toBeLessThanOrEqual(380);
    }

    await page.getByRole("tab", { name: "Predictors" }).click();
    const landscape = page.getByTestId("predictor-signal-landscape");
    await expect(landscape).toBeVisible();
    const predictorOffset = await firstContentOffset(
      page,
      "predictor-signal-landscape",
    );
    expect(predictorOffset).not.toBeNull();
    expect(predictorOffset!.visualTop).toBeLessThan(predictorOffset!.viewportHeight);
    if (viewport.name === "1536x864") {
      expect(predictorOffset!.offset).toBeLessThanOrEqual(380);
    }

    const marks = landscape.locator("[data-landscape-mark]");
    expect(await marks.count()).toBeGreaterThan(0);
    expect(await marks.count()).toBeLessThanOrEqual(60);
    await expect(landscape).not.toContainText("bad_flag");
    await expect(landscape).not.toContainText("RiskPerformance");

    const firstMark = marks.first();
    const selectedFeature = (await firstMark.getAttribute("aria-label"))
      ?.split(",")[0]
      .trim();
    await firstMark.click();
    if (selectedFeature) {
      await expect(page.getByTestId("eda-distribution-variable")).toHaveValue(
        selectedFeature,
      );
      await expect(page.getByTestId("eda-linked-selection-summary")).toContainText(
        selectedFeature,
      );
    }

    const lazyBoundary = page.getByTestId("lazy-predictor-secondary-insights");
    await expect(lazyBoundary).toBeAttached();
    if ((await lazyBoundary.getAttribute("data-load-state")) === "deferred") {
      await lazyBoundary.scrollIntoViewIfNeeded();
    }
    const secondary = page.getByTestId("predictor-secondary-insights");
    await expect(secondary).toBeVisible();
    await expect(secondary).toHaveAttribute(
      "data-aggregate-boundary",
      "single-batched-predictor-response",
    );
    for (const testId of [
      "event-rate-shape-gallery",
      "predictor-quality-matrix",
      "missingness-special-value-map",
    ]) {
      const visual = page.getByTestId(testId);
      await expect(visual).toBeVisible();
      await expect(visual).not.toContainText("bad_flag");
      await expect(visual).not.toContainText("RiskPerformance");
    }
    expect(await page.locator("[data-quality-cell]").count()).toBeGreaterThan(0);
    expect(await page.locator("[data-event-shape-line]").count()).toBeGreaterThan(0);

    const overflow = await page.evaluate(
      () => document.documentElement.scrollWidth - window.innerWidth,
    );
    expect(overflow).toBeLessThanOrEqual(1);
    expect(predictorRequests.length).toBeLessThanOrEqual(1);
    expect(runtimeErrors).toEqual([]);
    expect(failedResponses).toEqual([]);
  });
}

test("reduced motion renders every predictor visual in its final state", async ({
  page,
}) => {
  await page.emulateMedia({ reducedMotion: "reduce" });
  await requireAuthenticatedEda(page);
  await page.getByRole("tab", { name: "Predictors" }).click();
  await expect(page.getByTestId("predictor-signal-landscape")).toBeVisible();
  const lazyBoundary = page.getByTestId("lazy-predictor-secondary-insights");
  await lazyBoundary.scrollIntoViewIfNeeded();
  await expect(page.getByTestId("predictor-secondary-insights")).toBeVisible();
  await expect(page.locator("[data-landscape-mark]").first()).toHaveAttribute(
    "r",
    /[1-9]/,
  );
  await expect(page.locator("[data-quality-cell]").first()).toHaveAttribute(
    "width",
    /[1-9]/,
  );
  await expect(page.locator("[data-event-shape-line]").first()).toHaveAttribute(
    "stroke-dashoffset",
    "0",
  );
});

test("confirmation, MDD approval, and stale draft remain separate", async ({
  page,
}) => {
  const runtimeErrors: string[] = [];
  page.on("pageerror", (error) => runtimeErrors.push(error.message));
  page.on("console", (message) => {
    if (message.type() === "error") runtimeErrors.push(message.text());
  });
  await requireAuthenticatedEda(page);
  await page.getByRole("tab", { name: "Findings" }).click();

  const duplicateAction = page.getByLabel("Duplicate row action");
  if (await duplicateAction.count()) {
    await duplicateAction.selectOption("exclude");
    await page.getByRole("button", {
      name: "Save duplicate-row decision",
    }).click();
  }
  const commentary = page.getByLabel("Reviewer commentary");
  if (!(await commentary.inputValue()).trim()) {
    await commentary.fill(
      "Final EDA acceptance: governed findings reviewed for model-development carry-forward.",
    );
  }
  await page.getByLabel("Finding status").selectOption("accepted");
  await page.getByRole("button", { name: "Save to Evidence Center" }).click();
  const step02Path = new URL(page.url()).pathname;
  const scopedStep02 = step02Path.match(/^\/projects\/([^/]+)\/step02$/);
  expect(scopedStep02).not.toBeNull();
  const routeProjectId = scopedStep02![1];
  const confirmButton = page.getByTestId("eda-final-continue-button");
  await expect(confirmButton).toBeEnabled();
  const durableCompletion = page.waitForResponse(
    (response) =>
      response.request().method() === "PUT" &&
      new URL(response.url()).pathname ===
        `/api/projects/${routeProjectId}/workflow-state`,
    { timeout: 30_000 },
  );
  await confirmButton.click();
  expect((await durableCompletion).ok()).toBe(true);
  await expect
    .poll(() => new URL(page.url()).pathname, { timeout: 30_000 })
    .toBe(`/projects/${routeProjectId}/step03`);

  await page.goBack();
  await expect
    .poll(() => new URL(page.url()).pathname, { timeout: 30_000 })
    .toBe(`/projects/${routeProjectId}/step02`);
  await expect(page.getByTestId("eda-confirmation-status")).toHaveAttribute(
    "data-confirmation-state",
    "confirmed",
  );
  await page.goto("/model-document-studio");
  const liveLink = page.getByTestId("eda-documentation-live-link");
  await expect(liveLink).toBeVisible();
  await expect(page.getByTestId("eda-documentation-status")).toContainText(
    "Confirmed",
  );
  const approved = page.locator(
    '[aria-labelledby="approved-eda-documentation-title"]',
  );
  await expect(approved).toContainText("Confirmation ID");
  for (const label of [
    "Overview",
    "Target",
    "Predictors",
    "Relationships",
    "Stability and Segments",
    "Findings",
  ]) {
    await expect(approved).toContainText(label);
  }

  await page.goto("/step02");
  await page.getByRole("tab", { name: "Findings" }).click();
  await commentary.fill(
    `${await commentary.inputValue()}\nFinal-polish stale-state acceptance ${Date.now()}.`,
  );
  await page.getByRole("button", { name: "Save to Evidence Center" }).click();
  await expect(page.getByTestId("eda-confirmation-status")).toHaveAttribute(
    "data-confirmation-state",
    "stale",
  );
  await page.goto("/model-document-studio");
  await expect(page.getByTestId("eda-documentation-status")).toContainText(
    "Stale after upstream change",
  );
  await expect(
    page.locator('[aria-labelledby="approved-eda-documentation-title"]'),
  ).toContainText("Preserved");
  await expect(
    page.locator('[aria-labelledby="draft-eda-documentation-title"]'),
  ).toContainText("Not approved");
  expect(runtimeErrors).toEqual([]);
});
