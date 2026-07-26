import path from "node:path";
import { fileURLToPath } from "node:url";
import { test, expect } from "@playwright/test";
import { makeTestUser, registerUser } from "./helpers/auth";
import { createPredictiveModelingProject } from "./helpers/project";
import { fillProjectContextNarrative, CLASSIFICATION_NARRATIVE } from "./helpers/projectContext";
import { goNext } from "./helpers/workflow";
import { shot } from "./helpers/screenshots";
import { attachDiagnostics } from "./helpers/diagnostics";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const DATA_FILE = "e2e_audit_classification_dev.csv";

/**
 * CODE-DATAACQ-001..004 through the real UI. The Python badge must mirror the
 * backend's actual capability, the generated code must carry no placeholder
 * path, and SAS-compatible execution must bind to the active dataset identity.
 */
test.describe("Multi-Language Code Workspace", () => {
  async function openWorkspace(page: import("@playwright/test").Page, projectName: string) {
    await createPredictiveModelingProject(page, { name: projectName, modelId: `cws-${Date.now()}` });
    await fillProjectContextNarrative(page, CLASSIFICATION_NARRATIVE);
    await goNext(page, /\/step01/);
    await page.locator('input[type="file"]').setInputFiles(path.join(__dirname, "data", DATA_FILE));
    await page.waitForTimeout(4000);
    await page.getByLabel("Target Column").selectOption("Class");
    await page.waitForTimeout(2000);
    await page.getByRole("button", { name: /Data Access & Reproducibility Code|Code & Reproducibility/ }).click();
    await page.waitForTimeout(1500);
  }

  test("Python capability mirrors the backend and generated code carries no placeholder path", async ({ page }, testInfo) => {
    test.setTimeout(6 * 60_000);
    const { dump } = attachDiagnostics(page, testInfo);

    await registerUser(page, makeTestUser("codeWsPython"));
    await openWorkspace(page, "E2E Code Workspace Python");

    // The badge must agree with the backend's own capability report.
    const capability = await page.request.get("http://127.0.0.1:8001/api/python/capability");
    expect(capability.ok()).toBe(true);
    const capabilityBody = await capability.json();

    const runButton = page.getByRole("button", { name: "Run Python" });
    await expect(runButton).toBeVisible();

    // The badge lives on the Python language tab inside the workspace (scoped so
    // the unrelated "Python Loader" source card cannot match).
    // The tab's accessible name is the label concatenated with its badge
    // ("PythonExecutable", "PythonRuntime not configured", ...), which the
    // unrelated "Python Loader" source card never matches.
    const pythonTab = page.getByRole("button", { name: /^Python(Executable|Runtime|Checking)/ });
    const badgeText = (await pythonTab.textContent()) ?? "";

    // Type code so the Run button's own "has code" gate is satisfied; whether it
    // then enables must depend purely on the backend capability.
    const editor = page.locator("textarea:not([readonly])").first();
    await editor.fill('print("Dataset shape:", df.shape)');
    await page.waitForTimeout(500);

    if (capabilityBody.available) {
      expect(badgeText).toContain("Executable");
      await expect(runButton).toBeEnabled();
    } else {
      // CODE-DATAACQ-001: never claim Executable when the runtime is unavailable.
      expect(badgeText).not.toContain("Executable");
      expect(badgeText).toMatch(/Runtime not configured|Runtime misconfigured|Runtime disabled/);
      await expect(runButton).toBeDisabled();
    }
    await shot(page, testInfo, "01-python-runtime-capability");

    // When executable, the governed runtime must actually produce output.
    if (capabilityBody.available) {
      const [pyResponse] = await Promise.all([
        page.waitForResponse((r) => r.url().includes("/python/run"), { timeout: 120_000 }),
        runButton.click(),
      ]);
      expect(pyResponse.status()).toBe(200);
      const pyBody = await pyResponse.json();
      expect(pyBody.status, JSON.stringify(pyBody).slice(0, 400)).toBe("success");
      expect(pyBody.returnCode).toBe(0);
      expect(pyBody.stdout).toContain("Dataset shape:");
      expect(pyBody.runtimeState).toBe("executable");
      await shot(page, testInfo, "02-python-execution-result");
    }

    // CODE-DATAACQ-002: the generated Python must not contain the placeholder path.
    const workspaceText = (await page.locator("body").textContent()) ?? "";
    expect(workspaceText).not.toContain("path/to/dataset-library-export.csv");
    expect(workspaceText).not.toContain("dataset-library-export");

    await dump();
  });

  test("SAS-compatible execution binds to the active dataset and never to reg_train", async ({ page }, testInfo) => {
    test.setTimeout(6 * 60_000);
    const { dump } = attachDiagnostics(page, testInfo);

    await registerUser(page, makeTestUser("codeWsSas"));
    await openWorkspace(page, "E2E Code Workspace SAS");

    // Switch the workspace into SAS-compatible execution and select the SAS tab
    // (only the active language renders its Run action).
    await page.getByLabel("SAS execution mode").selectOption("compatible");
    await page.waitForTimeout(1000);
    await expect(page.getByText("ATLAS SAS-Compatible Local Execution").first()).toBeVisible();
    await page.getByRole("button", { name: /^SAS/ }).click();
    await page.waitForTimeout(1000);
    await shot(page, testInfo, "03-sas-compatible-mode");

    // The generated starter program must reference the active dataset, and must
    // never instruct a classification project to use a regression-era table.
    const bodyText = (await page.locator("body").textContent()) ?? "";
    expect(bodyText).not.toContain("reg_train");

    // Run the supported program and confirm honest, statement-level reporting.
    const [sasResponse] = await Promise.all([
      page.waitForResponse((r) => r.url().includes("/code/sas-compatible/run"), { timeout: 60_000 }),
      page.getByRole("button", { name: /Run SAS-Compatible/ }).click(),
    ]);
    expect(sasResponse.status()).toBe(200);
    const sasBody = await sasResponse.json();

    expect(sasBody.activeTable, "active SAS table must not be a regression default").not.toBe("reg_train");
    expect(JSON.stringify(sasBody)).not.toContain("reg_train");
    expect(sasBody.executionKind).toBe("sas_compatible_translated");
    expect(sasBody.engineNote).toContain("not a SASPy session");
    // Status and return code must agree.
    expect(["completed", "partial", "failed"]).toContain(sasBody.status);
    if (sasBody.status === "completed") {
      expect(sasBody.returnCode).toBe(0);
    } else {
      expect(sasBody.returnCode, "a non-completed run must not return code 0").not.toBe(0);
    }
    // Every statement is accounted for exactly once.
    const counted =
      sasBody.statementCounts.executed +
      sasBody.statementCounts.translated +
      sasBody.statementCounts.skipped_unsupported +
      sasBody.statementCounts.failed +
      sasBody.statementCounts.input_unavailable;
    expect(counted).toBe(sasBody.statementReport.length);
    await shot(page, testInfo, "04-sas-compatible-result");

    await dump();
  });
});
