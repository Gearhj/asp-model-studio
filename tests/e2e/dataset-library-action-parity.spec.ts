import { test, expect, type Page } from "@playwright/test";
import { attachDiagnostics } from "./helpers/diagnostics";
import { createPredictiveModelingProject } from "./helpers/project";
import { shot } from "./helpers/screenshots";

// CREDENTIALS, NOT A BYPASS.
//
// Commit 795178d ("Harden authentication and add security release gate") closed
// the two default-on authentication holes: public registration now returns 403
// and the X-ATLAS-USER-ID development header no longer authenticates. This spec
// therefore signs in with a REAL account supplied by the environment. It must
// never re-enable the dev header, self-register, or hardcode a password -- doing
// any of those would weaken the Phase 1 containment this walkthrough runs behind.
//
//   $env:ATLAS_E2E_EMAIL="you@example.com"; $env:ATLAS_E2E_PASSWORD="..."
//   npx playwright test --config tests/e2e/playwright.config.ts tests/e2e/dataset-library-action-parity.spec.ts
//
// The account must be able to see the dataset named by ATLAS_E2E_DATASET_ID
// (default: the governed CLASS_TRAIN registration).
const E2E_EMAIL = process.env.ATLAS_E2E_EMAIL || "";
const E2E_PASSWORD = process.env.ATLAS_E2E_PASSWORD || "";

// CREDENTIAL CONTAINMENT -- do not remove.
// Playwright's failure artifacts capture input values: an accessibility snapshot
// of the sign-in form renders the password field's value verbatim into
// error-context.md, and a trace records request post data. This spec therefore
// (a) authenticates through the login API so the credentials never enter the DOM
// at all, and (b) forces trace and video off so the login request body can never
// be recorded. Both are belt and braces on purpose. Must stay file top-level:
// Playwright rejects `video` inside a describe group.
test.use({ trace: "off", video: "off" });

// The complete CLASS_TRAIN registration, addressed by id.
const DATASET_ID = process.env.ATLAS_E2E_DATASET_ID || "ds_class_train_982c7a7d_35930";

/** Every action id the shared model can render, in model order. */
const ALL_ACTION_IDS = [
  "open",
  "link-project",
  "sql-studio",
  "analytics",
  "chart-studio",
  "share",
  "export-metadata",
  "archive",
] as const;

/** Reads the action ids actually rendered for one dataset, in one view. */
async function renderedActionIds(page: Page, testId: string): Promise<string[]> {
  const container = page.getByTestId(testId);
  await expect(container).toBeVisible({ timeout: 30_000 });
  return container.locator("[data-dataset-action]").evaluateAll((nodes) =>
    nodes.map((node) => node.getAttribute("data-dataset-action") || ""),
  );
}

test.describe("Dataset Library: Card and Detailed View action parity", () => {
  test.skip(
    !E2E_EMAIL || !E2E_PASSWORD,
    "Set ATLAS_E2E_EMAIL and ATLAS_E2E_PASSWORD to run this walkthrough. Authentication is hardened (795178d): self-registration and the dev-user header are disabled by design, so this spec needs a real account rather than a bypass.",
  );

  test("the same authorized action set is reachable from both views", async ({ page }, testInfo) => {
    test.setTimeout(5 * 60_000);
    const { log, dump } = attachDiagnostics(page, testInfo);

    // ---------- 1. Sign in with a real account -------------------------------
    // A genuine credentialed login against the real /api/auth/login endpoint --
    // NOT a development bypass. The resulting atlas_session cookie is stored in
    // this browser context, so the app is authenticated exactly as it would be
    // after using the form. Typing into the form is avoided only so the password
    // is never present in a DOM snapshot.
    const loginResponse = await page.request.post("http://127.0.0.1:8001/api/auth/login", {
      data: { email: E2E_EMAIL, password: E2E_PASSWORD },
    });
    expect(loginResponse.ok(), `sign-in failed with HTTP ${loginResponse.status()}`).toBeTruthy();
    const session = await loginResponse.json();
    expect(session.ok).toBeTruthy();
    // Identity is logged by display name only -- never the email or password.
    console.log("SIGNED_IN_AS_ROLE:", session.user?.role ?? "unknown");

    // ---------- 2. Open the Dataset Library ----------------------------------
    await page.goto("/datasets");
    await expect(page.getByRole("heading", { name: "Dataset Library" })).toBeVisible({ timeout: 60_000 });

    // Search narrows to CLASS_TRAIN so the row/card is unambiguous.
    const search = page.getByPlaceholder(/Search by dataset/i);
    await search.fill("CLASS_TRAIN");

    // ---------- 3-4. Detailed View: record the available action ids ----------
    await page.getByRole("button", { name: "Detailed View" }).click();
    const detailedIds = await renderedActionIds(page, `dataset-row-actions-${DATASET_ID}`);
    console.log("DETAILED_VIEW_ACTIONS:", JSON.stringify(detailedIds));
    for (const id of ALL_ACTION_IDS) {
      expect(detailedIds, `Detailed View is missing ${id}`).toContain(id);
    }
    await shot(page, testInfo, "parity-01-detailed-view-actions");

    // ---------- 5-6. Card View: the SAME ids, directly or via More Actions ----
    await page.getByRole("button", { name: "Card View" }).click();
    const cardPrimaryIds = await renderedActionIds(page, `dataset-card-actions-${DATASET_ID}`);
    console.log("CARD_VIEW_PRIMARY_ACTIONS:", JSON.stringify(cardPrimaryIds));
    expect(cardPrimaryIds).toEqual(expect.arrayContaining(["open", "link-project", "sql-studio"]));
    await shot(page, testInfo, "parity-02-card-view-primary-actions");

    // Search text must survive the view switch.
    await expect(search).toHaveValue("CLASS_TRAIN");

    const card = page.getByTestId(`dataset-card-actions-${DATASET_ID}`);
    const moreTrigger = card.getByTestId("dataset-more-actions-trigger");
    await expect(moreTrigger).toBeVisible();

    // Keyboard opening: focus the trigger and press Enter.
    await moreTrigger.focus();
    await page.keyboard.press("Enter");
    const menu = page.getByTestId("dataset-more-actions-menu");
    await expect(menu).toBeVisible();
    await expect(moreTrigger).toHaveAttribute("aria-expanded", "true");
    const overflowIds = await menu.locator("[data-dataset-action]").evaluateAll((nodes) =>
      nodes.map((node) => node.getAttribute("data-dataset-action") || ""),
    );
    console.log("CARD_VIEW_OVERFLOW_ACTIONS:", JSON.stringify(overflowIds));
    await shot(page, testInfo, "parity-03-card-view-more-actions-menu");

    // Arrow-key navigation moves focus inside the menu.
    await page.keyboard.press("ArrowDown");
    await expect(menu.locator(":focus")).toHaveCount(1);

    // Escape closes and returns focus to the trigger.
    await page.keyboard.press("Escape");
    await expect(menu).toBeHidden();
    await expect(moreTrigger).toBeFocused();

    // ---------- 6. PARITY ASSERTION ------------------------------------------
    const cardAll = [...cardPrimaryIds.filter((id) => id !== ""), ...overflowIds].filter(
      (id, index, list) => id && list.indexOf(id) === index,
    );
    expect(
      cardAll.slice().sort(),
      "Card View and Detailed View must expose the same action ids",
    ).toEqual(detailedIds.slice().sort());

    // ---------- 7. SQL Studio from Card View carries the dataset identity ----
    await page.getByTestId(`dataset-card-actions-${DATASET_ID}`).locator('[data-dataset-action="sql-studio"]').click();
    await expect(page).toHaveURL(new RegExp(`/sql-data-studio\\?datasetId=${DATASET_ID}`), { timeout: 60_000 });
    console.log("SQL_STUDIO_URL_FROM_CARD:", page.url());

    // ---------- 8. Link to Project: verify the TRUTHFUL authorized state ----
    //
    // The first credentialed run failed here for a real reason: the signed-in
    // user's current project was "Untitled ATLAS Project", which the backend
    // refuses with "You do not have access to link datasets to this project."
    // The action was offered anyway. It is now disabled with that exact reason.
    //
    // To exercise the SUCCESS path honestly, create a project through normal
    // product behaviour so the signed-in user owns it -- never by bypassing
    // authorization.
    await createPredictiveModelingProject(page, {
      name: `E2E Dataset Action Parity ${Date.now()}`,
      modelId: `00001-${Date.now()}`,
    });

    await page.goto("/datasets");
    await page.getByPlaceholder(/Search by dataset/i).fill("CLASS_TRAIN");

    // Detailed View state for the same action, for the cross-view comparison.
    await page.getByRole("button", { name: "Detailed View" }).click();
    const detailedLink = page
      .getByTestId(`dataset-row-actions-${DATASET_ID}`)
      .locator('[data-dataset-action="link-project"]');
    await expect(detailedLink).toBeVisible({ timeout: 30_000 });
    const detailedEnabled = await detailedLink.getAttribute("data-action-enabled");
    const detailedReason = await detailedLink.getAttribute("data-disabled-reason");

    await page.getByRole("button", { name: "Card View" }).click();
    const linkAction = page
      .getByTestId(`dataset-card-actions-${DATASET_ID}`)
      .locator('[data-dataset-action="link-project"]');
    await expect(linkAction).toBeVisible();
    const cardEnabled = await linkAction.getAttribute("data-action-enabled");
    const cardReason = await linkAction.getAttribute("data-disabled-reason");
    console.log("LINK_TO_PROJECT_STATE:", JSON.stringify({ detailedEnabled, cardEnabled, detailedReason, cardReason }));

    // Both views must agree on enabled state AND on the reason.
    expect(cardEnabled, "Link to Project enabled state must match across views").toBe(detailedEnabled);
    expect(cardReason, "Link to Project disabled reason must match across views").toBe(detailedReason);

    if (cardEnabled === "true") {
      expect(cardReason).toBeNull();

      // AUTHORITATIVE POSTCONDITION, not a transient toast.
      // The previous run could not tell success from a hang because it only
      // watched for toast text -- and the toast was in fact being erased by the
      // refresh that followed the mutation. Assert the request and the persisted
      // link instead; the toast is now only a secondary UX check.
      const [linkResponse] = await Promise.all([
        page.waitForResponse(
          (response) => /\/projects\/[^/]+\/datasets\/link$/.test(new URL(response.url()).pathname) && response.request().method() === "POST",
          { timeout: 60_000 },
        ),
        linkAction.click(),
      ]);
      const linkStatus = linkResponse.status();
      const linkBody = await linkResponse.text();
      console.log("LINK_POST_STATUS:", linkStatus);
      console.log("LINK_POST_BODY:", linkBody.slice(0, 400));
      expect(linkStatus, `link POST failed: ${linkBody.slice(0, 300)}`).toBe(200);
      expect(JSON.parse(linkBody).ok).toBeTruthy();

      // 2. The link must actually exist server-side afterwards.
      const projectId: string = JSON.parse(linkBody).link?.projectId;
      expect(projectId, "link response must name the project").toBeTruthy();
      const linksResponse = await page.request.get(
        `http://127.0.0.1:8001/api/projects/${projectId}/datasets`,
      );
      expect(linksResponse.ok(), `link listing failed with HTTP ${linksResponse.status()}`).toBeTruthy();
      const links = (await linksResponse.json()).links ?? [];
      console.log("PROJECT_LINK_COUNT:", links.length);
      expect(
        links.some((link: { datasetId?: string }) => link.datasetId === DATASET_ID),
        "the dataset must be linked to the project after the click",
      ).toBeTruthy();

      // 3. The UI must reflect it durably, in BOTH views.
      const cardContainer = page.getByTestId(`dataset-card-actions-${DATASET_ID}`);
      await expect(cardContainer).toHaveAttribute("data-linked-to-current-project", "true", { timeout: 60_000 });
      await page.getByRole("button", { name: "Detailed View" }).click();
      await expect(page.getByTestId(`dataset-row-actions-${DATASET_ID}`)).toHaveAttribute(
        "data-linked-to-current-project",
        "true",
        { timeout: 30_000 },
      );

      // 4. Secondary UX check: the product does intend a confirmation message.
      await page.getByRole("button", { name: "Card View" }).click();
      await expect(page.locator("body")).toContainText(/Linked "CLASS_TRAIN" to the current project/i, {
        timeout: 30_000,
      });
    } else {
      // Unauthorized: the action must state the server's real reason, and must
      // never silently fail after being offered.
      expect(cardReason, "a disabled Link to Project must explain why").toBeTruthy();
      expect(cardReason).toBe("You do not have access to link datasets to this project.");
    }

    // ---------- 9. No uncaught page errors caused by this phase --------------
    console.log("PARITY_FAILED_RESPONSES:", JSON.stringify(log.failedResponses));
    expect(log.pageErrors, `uncaught page errors: ${log.pageErrors.join(" | ")}`).toEqual([]);

    await dump();
  });
});
