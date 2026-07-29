import { expect, test } from "@playwright/test";

const viewports = [
  { name: "1366x768", width: 1366, height: 768 },
  { name: "1536x864", width: 1536, height: 864 },
  { name: "1920x1080", width: 1920, height: 1080 },
] as const;

for (const viewport of viewports) {
  test(`premium EDA composition remains usable at ${viewport.name}`, async ({
    page,
  }) => {
    const pageErrors: string[] = [];
    page.on("pageerror", (error) => pageErrors.push(error.message));
    page.on("console", (message) => {
      if (message.type() === "error") pageErrors.push(message.text());
    });
    await page.setViewportSize({
      width: viewport.width,
      height: viewport.height,
    });
    await page.goto("/step02");
    if (await page.getByRole("heading", { name: "Sign in to ATLAS" }).count()) {
      test.skip(
        true,
        "This acceptance specification requires an already authenticated browser state.",
      );
    }

    await expect(page.getByTestId("eda-documentation-impact")).toBeVisible();
    await expect(page.getByTestId("eda-confirmation-status")).toBeVisible();
    await expect(page.getByTestId("eda-dataset-fingerprint")).toBeVisible();

    await page.getByRole("tab", { name: "Target" }).click();
    await expect(page.getByTestId("target-governed-lineage")).toBeVisible();
    await expect(page.getByTestId("target-prevalence-ring")).toBeVisible();

    await page.getByRole("tab", { name: "Predictors" }).click();
    await expect(page.getByTestId("eda-iv-by-bin")).toBeVisible();
    await expect(
      page.getByTestId("eda-distribution-accessibility-alternative"),
    ).toBeVisible();

    await page.getByRole("tab", { name: "Relationships" }).click();
    const matrix = page.getByTestId("correlation-matrix-scroll-frame");
    await expect(matrix).toHaveAttribute("data-default-vertical-scroll", "false");
    await expect(page.getByTestId("eda-relationship-explorer-section")).toBeVisible();
    await expect(page.getByRole("button", { name: "3D Explorer" })).toBeVisible();

    const stickyFooter = page.locator("footer").last();
    const stage = page.locator(".eda-tab-stage");
    if ((await stickyFooter.count()) && (await stage.count())) {
      const [footerBox, stageBox] = await Promise.all([
        stickyFooter.boundingBox(),
        stage.boundingBox(),
      ]);
      if (footerBox && stageBox) {
        expect(stageBox.y + stageBox.height).toBeGreaterThan(footerBox.y);
      }
    }
    expect(pageErrors).toEqual([]);
  });
}
