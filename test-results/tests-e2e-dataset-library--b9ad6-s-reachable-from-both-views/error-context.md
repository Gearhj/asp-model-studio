# Instructions

- Following Playwright test failed.
- Explain why, be concise, respect Playwright best practices.
- Provide a snippet of code with the fix, if possible.

# Test info

- Name: tests\e2e\dataset-library-action-parity.spec.ts >> Dataset Library: Card and Detailed View action parity >> the same authorized action set is reachable from both views
- Location: tests\e2e\dataset-library-action-parity.spec.ts:35:3

# Error details

```
Error: page.goto: Protocol error (Page.navigate): Cannot navigate to invalid URL
Call log:
  - navigating to "/datasets", waiting until "load"

```

# Test source

```ts
  1   | import { test, expect, type Page } from "@playwright/test";
  2   | import { attachDiagnostics } from "./helpers/diagnostics";
  3   | import { shot } from "./helpers/screenshots";
  4   | 
  5   | // The complete CLASS_TRAIN registration, addressed by id.
  6   | const DATASET_ID = "ds_class_train_982c7a7d_35930";
  7   | 
  8   | /** Every action id the shared model can render, in model order. */
  9   | const ALL_ACTION_IDS = [
  10  |   "open",
  11  |   "link-project",
  12  |   "sql-studio",
  13  |   "analytics",
  14  |   "chart-studio",
  15  |   "share",
  16  |   "export-metadata",
  17  |   "archive",
  18  | ] as const;
  19  | 
  20  | /** Reads the action ids actually rendered for one dataset, in one view. */
  21  | async function renderedActionIds(page: Page, testId: string): Promise<string[]> {
  22  |   const container = page.getByTestId(testId);
  23  |   await expect(container).toBeVisible({ timeout: 30_000 });
  24  |   return container.locator("[data-dataset-action]").evaluateAll((nodes) =>
  25  |     nodes.map((node) => node.getAttribute("data-dataset-action") || ""),
  26  |   );
  27  | }
  28  | 
  29  | test.describe("Dataset Library: Card and Detailed View action parity", () => {
  30  |   // CLASS_TRAIN is owned by the local development user; the dataset ACL correctly
  31  |   // refuses anyone else, so the walkthrough runs AS the owner rather than
  32  |   // weakening the ACL.
  33  |   test.use({ extraHTTPHeaders: { "X-ATLAS-USER-ID": "local-user" } });
  34  | 
  35  |   test("the same authorized action set is reachable from both views", async ({ page }, testInfo) => {
  36  |     test.setTimeout(5 * 60_000);
  37  |     const { log, dump } = attachDiagnostics(page, testInfo);
  38  | 
  39  |     // ---------- 1-2. Open the Dataset Library ---------------------------------
> 40  |     await page.goto("/datasets");
      |                ^ Error: page.goto: Protocol error (Page.navigate): Cannot navigate to invalid URL
  41  |     await expect(page.getByRole("heading", { name: "Dataset Library" })).toBeVisible({ timeout: 60_000 });
  42  | 
  43  |     // Search narrows to CLASS_TRAIN so the row/card is unambiguous.
  44  |     const search = page.getByPlaceholder(/Search by dataset/i);
  45  |     await search.fill("CLASS_TRAIN");
  46  | 
  47  |     // ---------- 3-4. Detailed View: record the available action ids ----------
  48  |     await page.getByRole("button", { name: "Detailed View" }).click();
  49  |     const detailedIds = await renderedActionIds(page, `dataset-row-actions-${DATASET_ID}`);
  50  |     console.log("DETAILED_VIEW_ACTIONS:", JSON.stringify(detailedIds));
  51  |     for (const id of ALL_ACTION_IDS) {
  52  |       expect(detailedIds, `Detailed View is missing ${id}`).toContain(id);
  53  |     }
  54  |     await shot(page, testInfo, "parity-01-detailed-view-actions");
  55  | 
  56  |     // ---------- 5-6. Card View: the SAME ids, directly or via More Actions ----
  57  |     await page.getByRole("button", { name: "Card View" }).click();
  58  |     const cardPrimaryIds = await renderedActionIds(page, `dataset-card-actions-${DATASET_ID}`);
  59  |     console.log("CARD_VIEW_PRIMARY_ACTIONS:", JSON.stringify(cardPrimaryIds));
  60  |     expect(cardPrimaryIds).toEqual(expect.arrayContaining(["open", "link-project", "sql-studio"]));
  61  |     await shot(page, testInfo, "parity-02-card-view-primary-actions");
  62  | 
  63  |     // Search text must survive the view switch.
  64  |     await expect(search).toHaveValue("CLASS_TRAIN");
  65  | 
  66  |     const card = page.getByTestId(`dataset-card-actions-${DATASET_ID}`);
  67  |     const moreTrigger = card.getByTestId("dataset-more-actions-trigger");
  68  |     await expect(moreTrigger).toBeVisible();
  69  | 
  70  |     // Keyboard opening: focus the trigger and press Enter.
  71  |     await moreTrigger.focus();
  72  |     await page.keyboard.press("Enter");
  73  |     const menu = page.getByTestId("dataset-more-actions-menu");
  74  |     await expect(menu).toBeVisible();
  75  |     await expect(moreTrigger).toHaveAttribute("aria-expanded", "true");
  76  |     const overflowIds = await menu.locator("[data-dataset-action]").evaluateAll((nodes) =>
  77  |       nodes.map((node) => node.getAttribute("data-dataset-action") || ""),
  78  |     );
  79  |     console.log("CARD_VIEW_OVERFLOW_ACTIONS:", JSON.stringify(overflowIds));
  80  |     await shot(page, testInfo, "parity-03-card-view-more-actions-menu");
  81  | 
  82  |     // Arrow-key navigation moves focus inside the menu.
  83  |     await page.keyboard.press("ArrowDown");
  84  |     await expect(menu.locator(":focus")).toHaveCount(1);
  85  | 
  86  |     // Escape closes and returns focus to the trigger.
  87  |     await page.keyboard.press("Escape");
  88  |     await expect(menu).toBeHidden();
  89  |     await expect(moreTrigger).toBeFocused();
  90  | 
  91  |     // ---------- 6. PARITY ASSERTION ------------------------------------------
  92  |     const cardAll = [...cardPrimaryIds.filter((id) => id !== ""), ...overflowIds].filter(
  93  |       (id, index, list) => id && list.indexOf(id) === index,
  94  |     );
  95  |     expect(
  96  |       cardAll.slice().sort(),
  97  |       "Card View and Detailed View must expose the same action ids",
  98  |     ).toEqual(detailedIds.slice().sort());
  99  | 
  100 |     // ---------- 7. SQL Studio from Card View carries the dataset identity ----
  101 |     await page.getByTestId(`dataset-card-actions-${DATASET_ID}`).locator('[data-dataset-action="sql-studio"]').click();
  102 |     await expect(page).toHaveURL(new RegExp(`/sql-data-studio\\?datasetId=${DATASET_ID}`), { timeout: 60_000 });
  103 |     console.log("SQL_STUDIO_URL_FROM_CARD:", page.url());
  104 | 
  105 |     // ---------- 8. Return and exercise Link to Project from Card View --------
  106 |     await page.goto("/datasets");
  107 |     await page.getByPlaceholder(/Search by dataset/i).fill("CLASS_TRAIN");
  108 |     await page.getByRole("button", { name: "Card View" }).click();
  109 |     const linkAction = page
  110 |       .getByTestId(`dataset-card-actions-${DATASET_ID}`)
  111 |       .locator('[data-dataset-action="link-project"]');
  112 |     await expect(linkAction).toBeVisible();
  113 |     const linkEnabled = await linkAction.getAttribute("data-action-enabled");
  114 |     console.log("LINK_TO_PROJECT_ENABLED_FROM_CARD:", linkEnabled);
  115 |     if (linkEnabled === "true") {
  116 |       await linkAction.click();
  117 |       // Either a success or an honest failure message -- never a silent no-op.
  118 |       await expect(page.locator("body")).toContainText(/Linked "CLASS_TRAIN"|could not link/i, { timeout: 60_000 });
  119 |     } else {
  120 |       // Disabled must state why, in the same words Detailed View uses.
  121 |       expect(await linkAction.getAttribute("data-disabled-reason")).toBeTruthy();
  122 |     }
  123 | 
  124 |     // ---------- 9. No uncaught page errors caused by this phase --------------
  125 |     console.log("PARITY_FAILED_RESPONSES:", JSON.stringify(log.failedResponses));
  126 |     expect(log.pageErrors, `uncaught page errors: ${log.pageErrors.join(" | ")}`).toEqual([]);
  127 | 
  128 |     await dump();
  129 |   });
  130 | });
  131 | 
```