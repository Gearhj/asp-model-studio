import fs from "node:fs";
import path from "node:path";
import { expect, test, type Page } from "@playwright/test";

type LifecycleProbe = {
  providerStatuses: string[];
  step00Mounts: number;
  step00Unmounts: number;
  projectContextEvents: number;
};

type NetworkRecord = {
  method: string;
  pathname: string;
  search: string;
  body_keys?: string[];
  metadata_keys?: string[];
};

function requiredEnvironment(name: string): string {
  const value = process.env[name]?.trim();
  if (!value) throw new Error(`${name} is required.`);
  return value;
}

const baseURL = requiredEnvironment("ATLAS_E2E_BASE_URL");
const sessionCookie = requiredEnvironment("ATLAS_RESTART_SESSION_COOKIE");
const projectId = requiredEnvironment("ATLAS_RESTART_PROJECT_ID");
const datasetId = requiredEnvironment("ATLAS_RESTART_DATASET_ID");
const datasetVersionId = requiredEnvironment("ATLAS_RESTART_DATASET_VERSION_ID");
const activationRevision = Number(requiredEnvironment("ATLAS_RESTART_ACTIVATION_REVISION"));
const cycleLabel = requiredEnvironment("ATLAS_RESTART_CYCLE_LABEL");
const resultPath = requiredEnvironment("ATLAS_RESTART_BROWSER_RESULT_PATH");

function routeFor(step: string): string {
  return `/projects/${encodeURIComponent(projectId)}/${step}`;
}

async function installLifecycleProbe(page: Page): Promise<void> {
  await page.addInitScript(() => {
    const probe: LifecycleProbe = {
      providerStatuses: [],
      step00Mounts: 0,
      step00Unmounts: 0,
      projectContextEvents: 0,
    };
    (window as any).__atlasRestartLifecycleProbe = probe;
    window.addEventListener("atlas-project-context-updated", () => {
      probe.projectContextEvents += 1;
    });

    let step00Present = false;
    let lastStatus = "";
    const sample = () => {
      const present = Boolean(document.querySelector('[data-testid="model-identity-card"]'));
      if (present && !step00Present) probe.step00Mounts += 1;
      if (!present && step00Present) probe.step00Unmounts += 1;
      step00Present = present;

      const status =
        document
          .querySelector('[data-testid="atlas-breadcrumb"]')
          ?.getAttribute("data-project-context-status") ?? "";
      if (status && status !== lastStatus) {
        probe.providerStatuses.push(status);
        lastStatus = status;
      }
    };
    const start = () => {
      sample();
      new MutationObserver(sample).observe(document.documentElement, {
        childList: true,
        subtree: true,
        attributes: true,
        attributeFilter: ["data-testid", "data-project-context-status"],
      });
    };
    if (document.documentElement) start();
    else document.addEventListener("DOMContentLoaded", start, { once: true });
  });
}

test("actual project-scoped composition remains exact after an isolated backend restart", async ({
  browser,
}) => {
  const context = await browser.newContext();
  await context.addCookies([
    {
      name: "atlas_session",
      value: sessionCookie,
      domain: "127.0.0.1",
      path: "/",
      httpOnly: true,
      sameSite: "Lax",
    },
  ]);
  const page = await context.newPage();
  await installLifecycleProbe(page);

  const pageErrors: string[] = [];
  const requests: NetworkRecord[] = [];
  const forbiddenRequests: NetworkRecord[] = [];
  const finalHoldoutDataRequests: NetworkRecord[] = [];
  const authorityMutationRequests: NetworkRecord[] = [];
  const compatibilityMetadataWrites: NetworkRecord[] = [];
  const identityResponses: Array<Record<string, unknown>> = [];
  const overviewResponses: Array<{ status: number; payload: Record<string, any> }> = [];

  page.on("pageerror", (error) => pageErrors.push(error.message));
  page.on("request", (request) => {
    const url = new URL(request.url());
    if (!url.pathname.startsWith("/api/")) return;
    const body: Record<string, any> = (() => {
      try {
        const parsed = request.postDataJSON();
        return parsed && typeof parsed === "object"
          ? (parsed as Record<string, any>)
          : {};
      } catch {
        return {};
      }
    })();
    const record: NetworkRecord = {
      method: request.method().toUpperCase(),
      pathname: url.pathname,
      search: url.search,
      ...(Object.keys(body).length
        ? {
            body_keys: Object.keys(body).sort(),
            metadata_keys:
              body.metadata && typeof body.metadata === "object"
                ? Object.keys(body.metadata).sort()
                : [],
          }
        : {}),
    };
    requests.push(record);
    const routeText = `${record.pathname}${record.search}`.toLowerCase();
    const bodyText = (request.postData() ?? "").toLowerCase();
    if (
      /\/(?:model-training|training|evaluate|evaluation|interpretation|scoring|model-registry|final-model)(?:\/|$)/.test(
        routeText,
      )
    ) {
      forbiddenRequests.push(record);
    }
    if (
      /final[-_]holdout/.test(`${routeText} ${bodyText}`) &&
      !routeText.includes("/analysis-partitions/")
    ) {
      finalHoldoutDataRequests.push(record);
    }
    if (
      record.method !== "GET" &&
      (
        routeText === "/api/datasets/upload" ||
        /\/api\/datasets\/[^/]+\/versions\/[^/]+\/activate$/.test(routeText) ||
        routeText === "/api/data/set_target" ||
        routeText === "/api/analysis-partitions/confirm" ||
        /\/api\/projects\/[^/]+\/datasets\/link$/.test(routeText)
      )
    ) {
      authorityMutationRequests.push(record);
    }
    if (routeText === `/api/projects/${projectId}`.toLowerCase() && record.method === "PUT") {
      const metadata =
        body.metadata && typeof body.metadata === "object"
          ? (body.metadata as Record<string, unknown>)
          : {};
      const carriesAuthority = [
        "activeSelection",
        "active_selection",
        "links",
        "datasetId",
        "dataset_id",
        "datasetVersionId",
        "dataset_version_id",
      ].some((key) => key in body || key in metadata) || [
        "projectContext",
        "project_context",
        "modelingDataset",
        "modeling_dataset",
      ].some((key) => key in metadata);
      if (carriesAuthority) authorityMutationRequests.push(record);
      else compatibilityMetadataWrites.push(record);
    }
  });
  page.on("response", async (response) => {
    const url = new URL(response.url());
    if (url.pathname === "/api/data/active-identity" && response.status() === 200) {
      identityResponses.push(await response.json());
    }
    if (url.pathname === "/api/eda/workspace/overview") {
      overviewResponses.push({ status: response.status(), payload: await response.json() });
    }
  });

  await page.goto(routeFor("step00"), { waitUntil: "domcontentloaded" });
  await expect(page).not.toHaveURL(/\/login(?:\?|$)/);
  await expect(page.getByTestId("model-identity-card")).toBeVisible();
  await expect(page.getByTestId("atlas-breadcrumb")).toHaveAttribute(
    "data-project-context-status",
    "ready",
  );
  await expect.poll(() => identityResponses.length).toBeGreaterThan(0);

  await page.waitForTimeout(1_000);
  const step00RequestCount = requests.length;
  await page.waitForTimeout(1_000);
  expect(requests.length, "Step00 must settle without a hydration request loop.").toBe(
    step00RequestCount,
  );
  const step00Probe = await page.evaluate(
    () => (window as any).__atlasRestartLifecycleProbe as LifecycleProbe,
  );
  expect(step00Probe.step00Mounts).toBe(1);
  expect(step00Probe.step00Unmounts).toBe(0);
  expect(step00Probe.projectContextEvents).toBe(0);
  expect(step00Probe.providerStatuses.at(-1)).toBe("ready");

  await page.goto(routeFor("step01"), { waitUntil: "domcontentloaded" });
  await expect(page.getByRole("heading", { name: "Step 1: Data Acquisition" })).toBeVisible();
  await expect(page.getByTestId("dataset-persistence-card")).toHaveAttribute(
    "data-persistence-mode",
    "registered-status",
  );
  await expect(page.getByTestId("already-linked-badge")).toBeVisible();
  await expect(page.getByTestId("dataset-persistence-card")).toContainText(datasetId);
  await expect(page.getByTestId("dataset-persistence-card")).toContainText(datasetVersionId);
  await expect(page.getByTestId("durable-dataset-activation-revision")).toContainText(
    String(activationRevision),
  );

  await page.goto(`${routeFor("step02")}?edaTab=overview`, {
    waitUntil: "domcontentloaded",
  });
  await expect(page.getByRole("heading", { name: "Step 2: Exploratory Data Analysis" })).toBeVisible();
  await expect(page.getByTestId("eda-overview-launch-surface")).toBeVisible();
  await expect.poll(() => overviewResponses.length).toBeGreaterThan(0);
  await expect(page.getByTestId("atlas-safe-error-boundary")).toHaveCount(0);

  const identity = identityResponses.at(-1)!;
  expect(identity.project_id).toBe(projectId);
  expect(identity.dataset_id).toBe(datasetId);
  expect(identity.dataset_version_id).toBe(datasetVersionId);
  expect(Number(identity.activation_revision)).toBe(activationRevision);

  const overview = overviewResponses.at(-1)!;
  expect(overview.status).toBe(200);
  expect(overview.payload.project_id).toBe(projectId);
  expect(overview.payload.dataset_id).toBe(datasetId);
  expect(overview.payload.dataset_version_id).toBe(datasetVersionId);
  expect(overview.payload.scope).toBe("development_population");
  expect(overview.payload.analysis_scope?.decisionReady).toBe(true);
  expect(overview.payload.analysis_scope?.finalHoldoutAccessed).toBe(false);
  expect(overview.payload.analysis_scope?.finalHoldoutUsedForSelection).toBe(false);

  expect(pageErrors).toEqual([]);
  expect(forbiddenRequests).toEqual([]);
  expect(finalHoldoutDataRequests).toEqual([]);
  expect(authorityMutationRequests).toEqual([]);

  fs.mkdirSync(path.dirname(resultPath), { recursive: true });
  fs.writeFileSync(
    resultPath,
    JSON.stringify(
      {
        status: "passed",
        cycle_label: cycleLabel,
        project_id: projectId,
        dataset_id: datasetId,
        dataset_version_id: datasetVersionId,
        activation_revision: activationRevision,
        step00: {
          mounts: step00Probe.step00Mounts,
          unmounts: step00Probe.step00Unmounts,
          project_context_events: step00Probe.projectContextEvents,
          provider_statuses: step00Probe.providerStatuses,
          settled_request_count: step00RequestCount,
        },
        step01: { exact_identity_rendered: true },
        step02: {
          rendered: true,
          overview_status: overview.status,
          scope: overview.payload.scope,
          final_holdout_accessed: false,
          final_holdout_used_for_selection: false,
        },
        api_request_count: requests.length,
        forbidden_request_count: 0,
        final_holdout_data_request_count: 0,
        authority_mutation_request_count: 0,
        compatibility_metadata_write_count: compatibilityMetadataWrites.length,
        compatibility_metadata_writes: compatibilityMetadataWrites,
      },
      null,
      2,
    ),
    "utf8",
  );

  await context.close();
});
