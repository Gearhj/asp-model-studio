import {
  expect,
  test,
  type Page,
  type Route,
} from "@playwright/test";

const USER_ID = "project-context-test-user";
const DATASET_ID = "ds_project_context_fixture";
const VERSION_ID = "v_project_context_fixture_001";

type ProjectFixture = {
  projectId: string;
  projectName: string;
  workflowType?: string;
  projectStatus?: number;
  waitForProject?: Promise<void>;
  waitForProjectPut?: (input: {
    putNumber: number;
    projectId: string;
    projectContext: Record<string, unknown>;
  }) => Promise<void>;
  allowProjectMetadataWrites?: boolean;
  allowProjectCompletionWrites?: boolean;
  hasStoredProjectContext?: boolean;
  projectContextOverrides?: Record<string, unknown>;
  ambiguousProjectContextAckOnce?: boolean;
  sortStoredJsonKeys?: boolean;
};

type RequestStats = {
  projectGets: Record<string, number>;
  workflowGets: Record<string, number>;
  identityGets: Record<string, number>;
  sampleGets: Record<string, number>;
  projectPuts: Array<{
    projectId: string;
    revision: string;
    projectName: string;
    projectContext: Record<string, unknown>;
  }>;
  completionSideEffects: Array<{
    method: string;
    pathname: string;
    body: Record<string, unknown>;
  }>;
  nonGetRequests: Array<{ method: string; pathname: string }>;
};

function projectRecord(
  projectId: string,
  projectName: string,
  workflowType = "predictive-modeling",
) {
  const identity = {
    projectId,
    datasetId: DATASET_ID,
    datasetVersionId: VERSION_ID,
  };
  return {
    projectId,
    projectName,
    projectType: "predictive-modeling",
    workflowType,
    ownerUserId: USER_ID,
    status: "active",
    activeSelection: identity,
    metadata: {
      modelId: `model-${projectId}`,
      hasDataset: true,
      projectTools: {},
      projectContextRevision: "1000-initial",
      projectContextSavedAt: "2026-08-02T12:00:30.000Z",
      projectContext: {
        modelId: `model-${projectId}`,
        projectName,
        modelType: "generic classification",
        modelTypeSelection: "Generic Binary Classification",
        businessObjective: "Use a governed test fixture to validate Project Context lifecycle behavior.",
        intendedModelUse: "Support isolated browser acceptance without touching live project authorities.",
        targetDefinition: "Predict the synthetic fixture event for lifecycle testing.",
        populationDefinition: "Synthetic records created only for the isolated browser fixture.",
        observationWindow: "Synthetic observations available before the fixture decision point.",
        performanceWindow: "Synthetic outcomes observed after the fixture decision point.",
      },
    },
    createdAt: "2026-08-02T12:00:00.000Z",
    updatedAt: "2026-08-02T12:01:00.000Z",
  };
}

async function installProjectContextLifecycleProbe(page: Page) {
  await page.addInitScript(() => {
    const probe = {
      mountCount: 0,
      unmountCount: 0,
      eventDispatchCount: 0,
      hydrationStartCount: 0,
      hydrationCompleteCount: 0,
      providerStatuses: [] as string[],
      lastEventDetail: null as Record<string, unknown> | null,
    };
    (window as any).__atlasProjectContextLifecycle = probe;
    window.addEventListener("atlas-project-context-updated", (event) => {
      probe.eventDispatchCount += 1;
      probe.lastEventDetail = (event as CustomEvent).detail ?? null;
    });

    let modelCardPresent = false;
    let lastProviderStatus = "";
    const sample = () => {
      const card = Boolean(document.querySelector('[data-testid="model-identity-card"]'));
      if (card && !modelCardPresent) {
        probe.mountCount += 1;
        probe.hydrationCompleteCount += 1;
      } else if (!card && modelCardPresent) {
        probe.unmountCount += 1;
      }
      modelCardPresent = card;

      const breadcrumb = document.querySelector('[data-testid="atlas-breadcrumb"]');
      const status = breadcrumb?.getAttribute("data-project-context-status") || "";
      if (status && status !== lastProviderStatus) {
        probe.providerStatuses.push(status);
        if (status === "resolving") probe.hydrationStartCount += 1;
        lastProviderStatus = status;
      }
    };
    const start = () => {
      sample();
      new MutationObserver(sample).observe(document.documentElement, {
        childList: true,
        subtree: true,
        attributes: true,
        attributeFilter: ["data-project-context-status"],
      });
    };
    if (document.documentElement) start();
    else document.addEventListener("DOMContentLoaded", start, { once: true });
  });
}

type DraftCacheOperation = {
  operation: "set" | "remove";
  value: string | null;
};

function projectContextDraftKey(projectId: string, userId = USER_ID) {
  return `atlas:project-context-draft:${encodeURIComponent(userId)}:${encodeURIComponent(projectId)}`;
}

async function installDraftCacheProbe(page: Page, projectId: string) {
  const draftKey = projectContextDraftKey(projectId);
  await page.addInitScript(({ key }) => {
    const operations: Array<{ operation: "set" | "remove"; value: string | null }> = [];
    (window as any).__atlasProjectContextDraftOperations = operations;
    const originalSetItem = Storage.prototype.setItem;
    const originalRemoveItem = Storage.prototype.removeItem;
    Storage.prototype.setItem = function setItem(storageKey: string, value: string) {
      if (storageKey === key) operations.push({ operation: "set", value });
      return originalSetItem.call(this, storageKey, value);
    };
    Storage.prototype.removeItem = function removeItem(storageKey: string) {
      if (storageKey === key) operations.push({ operation: "remove", value: null });
      return originalRemoveItem.call(this, storageKey);
    };
  }, { key: draftKey });
}

async function readProjectContextDraft(page: Page, projectId: string) {
  const draftKey = projectContextDraftKey(projectId);
  return page.evaluate((key) => {
    const raw = localStorage.getItem(key);
    return raw ? JSON.parse(raw) : null;
  }, draftKey) as Promise<{
    context?: Record<string, unknown>;
    savedAt?: string;
  } | null>;
}

async function readDraftCacheOperations(page: Page): Promise<DraftCacheOperation[]> {
  return page.evaluate(
    () => [...((window as any).__atlasProjectContextDraftOperations ?? [])],
  );
}

function deferredAcknowledgement() {
  let release = () => undefined;
  const wait = new Promise<void>((resolve) => {
    release = resolve;
  });
  return { wait, release };
}

function sortJsonKeys(value: unknown): any {
  if (Array.isArray(value)) return value.map((item) => sortJsonKeys(item));
  if (value && typeof value === "object") {
    return Object.fromEntries(
      Object.keys(value as Record<string, unknown>)
        .sort()
        .map((key) => [key, sortJsonKeys((value as Record<string, unknown>)[key])]),
    );
  }
  return value;
}

function workflowState(projectId: string, workflowId = "predictive-modeling") {
  return {
    projectId,
    currentStepId: "step01",
    updatedAt: "2026-08-02T12:02:00.000Z",
    workflowStatus: {
      workflowId,
      projectType: "predictive-modeling",
      hasDataset: true,
      datasetIdentity: {
        project_id: projectId,
        dataset_id: DATASET_ID,
        dataset_version_id: VERSION_ID,
        activation_revision: 1,
      },
      steps: {
        step00: "complete",
        step01: "in_progress",
        step02: "pending",
      },
    },
  };
}

function activeIdentity(projectId: string) {
  return {
    ok: true,
    project_id: projectId,
    dataset_id: DATASET_ID,
    dataset_version_id: VERSION_ID,
    activation_revision: 1,
    dataset_version_label: "Project-context fixture version",
    dataset_source_type: "dataset-library",
    target: "bad_flag",
  };
}

async function fulfillJson(
  route: Route,
  status: number,
  body: Record<string, unknown>,
) {
  await route.fulfill({
    status,
    contentType: "application/json",
    headers: {
      "Access-Control-Allow-Origin": "http://127.0.0.1:5174",
      "Access-Control-Allow-Credentials": "true",
    },
    body: JSON.stringify(body),
  });
}

async function installProjectAuthorityMocks(
  page: Page,
  fixtures: ProjectFixture[],
  initialWorkflowState?: Record<string, unknown>,
  authState: { userId: string } = { userId: USER_ID },
  legacyProjectContext?: Record<string, unknown>,
) {
  const fixtureById = new Map(fixtures.map((fixture) => [fixture.projectId, fixture]));
  const stats: RequestStats = {
    projectGets: {},
    workflowGets: {},
    identityGets: {},
    sampleGets: {},
    projectPuts: [],
    completionSideEffects: [],
    nonGetRequests: [],
  };
  const records = new Map(fixtures.map((fixture) => {
    const stored = projectRecord(
      fixture.projectId,
      fixture.projectName,
      fixture.workflowType,
    );
    if (fixture.hasStoredProjectContext === false) {
      delete stored.metadata.projectContext;
      delete stored.metadata.projectContextRevision;
      delete stored.metadata.projectContextSavedAt;
    } else if (fixture.projectContextOverrides) {
      stored.metadata.projectContext = {
        ...stored.metadata.projectContext,
        ...fixture.projectContextOverrides,
      };
    }
    return [fixture.projectId, stored];
  }));
  const ambiguousAcknowledgementsSent = new Set<string>();

  await page.addInitScript(({ seed, legacyContext }) => {
    localStorage.clear();
    sessionStorage.clear();
    if (legacyContext) {
      localStorage.setItem("modeling-tool-project-context", JSON.stringify(legacyContext));
    }
    if (seed) {
      sessionStorage.setItem(
        "ds-workflow-store",
        JSON.stringify({ state: seed, version: 7 }),
      );
    }
  }, {
    seed: initialWorkflowState ?? null,
    legacyContext: legacyProjectContext ?? null,
  });

  await page.route("**/api/**", async (route) => {
    const request = route.request();
    const url = new URL(request.url());
    const method = request.method().toUpperCase();
    const pathname = url.pathname;

    if (pathname === "/api/auth/logout" && method === "POST") {
      authState.userId = "";
      await fulfillJson(route, 200, { ok: true });
      return;
    }

    const projectMatch = pathname.match(/^\/api\/projects\/([^/]+)$/);
    if (method === "PUT" && projectMatch) {
      const projectId = decodeURIComponent(projectMatch[1]);
      const fixture = fixtureById.get(projectId);
      const body = request.postDataJSON() as Record<string, any>;
      const isProjectContextWrite = Boolean(body.metadata?.projectContext);
      const allowed = isProjectContextWrite
        ? fixture?.allowProjectMetadataWrites
        : fixture?.allowProjectCompletionWrites;
      if (!allowed) {
        stats.nonGetRequests.push({ method, pathname });
        await fulfillJson(route, 409, {
          ok: false,
          detail: "Mutation forbidden by project-context hydration test",
        });
        return;
      }
      const previous = records.get(projectId)!;
      const metadata = {
        ...previous.metadata,
        ...(body.metadata ?? {}),
      };
      if (fixture?.sortStoredJsonKeys) {
        metadata.projectContext = sortJsonKeys(metadata.projectContext);
      }
      const projectContext = {
        ...((metadata.projectContext ?? {}) as Record<string, unknown>),
      };
      const updated = {
        ...previous,
        projectName: String(body.projectName || previous.projectName),
        metadata,
        updatedAt: String(metadata.projectContextSavedAt || previous.updatedAt),
      };
      records.set(projectId, updated);
      if (!isProjectContextWrite) {
        stats.completionSideEffects.push({ method, pathname, body });
        await fulfillJson(route, 200, { ok: true, project: updated });
        return;
      }
      stats.projectPuts.push({
        projectId,
        revision: String(metadata.projectContextRevision || ""),
        projectName: updated.projectName,
        projectContext,
      });
      await fixture.waitForProjectPut?.({
        putNumber: stats.projectPuts.length,
        projectId,
        projectContext,
      });
      if (
        fixture.ambiguousProjectContextAckOnce
        && !ambiguousAcknowledgementsSent.has(projectId)
      ) {
        ambiguousAcknowledgementsSent.add(projectId);
        await fulfillJson(route, 200, {
          ok: true,
          project: {
            ...updated,
            metadata: { ...metadata, modelId: "ambiguous-acknowledgement" },
          },
        });
        return;
      }
      await fulfillJson(route, 200, { ok: true, project: updated });
      return;
    }

    if (pathname === "/api/evidence" && method === "POST") {
      const body = request.postDataJSON() as Record<string, unknown>;
      const projectId = String(body.projectId ?? "");
      const fixture = fixtureById.get(projectId);
      if (fixture?.allowProjectCompletionWrites) {
        stats.completionSideEffects.push({ method, pathname, body });
        await fulfillJson(route, 200, {
          ok: true,
          evidence: {
            ...body,
            evidenceId: `evidence-${stats.completionSideEffects.length}`,
            projectId,
            createdAt: "2026-08-02T12:10:00.000Z",
            updatedAt: "2026-08-02T12:10:00.000Z",
          },
        });
        return;
      }
    }

    const completionProjectMatch = pathname.match(
      /^\/api\/projects\/([^/]+)\/(evidence|decisions)$/,
    );
    if (method === "POST" && completionProjectMatch) {
      const projectId = decodeURIComponent(completionProjectMatch[1]);
      const fixture = fixtureById.get(projectId);
      if (fixture?.allowProjectCompletionWrites) {
        const body = request.postDataJSON() as Record<string, unknown>;
        stats.completionSideEffects.push({ method, pathname, body });
        await fulfillJson(route, 200, {
          ok: true,
          [completionProjectMatch[2] === "evidence" ? "evidence" : "decision"]: body,
        });
        return;
      }
    }

    const workflowWriteMatch = pathname.match(
      /^\/api\/projects\/([^/]+)\/workflow-state$/,
    );
    if (method === "PUT" && workflowWriteMatch) {
      const projectId = decodeURIComponent(workflowWriteMatch[1]);
      const fixture = fixtureById.get(projectId);
      if (fixture?.allowProjectCompletionWrites) {
        const body = request.postDataJSON() as Record<string, unknown>;
        stats.completionSideEffects.push({ method, pathname, body });
        await fulfillJson(route, 200, { ok: true, workflowState: body });
        return;
      }
    }

    if (method !== "GET") {
      stats.nonGetRequests.push({ method, pathname });
      await fulfillJson(route, 409, {
        ok: false,
        detail: "Mutation forbidden by project-context hydration test",
      });
      return;
    }

    if (pathname === "/api/auth/me") {
      if (!authState.userId) {
        await fulfillJson(route, 401, { ok: false, detail: "Signed out" });
        return;
      }
      await fulfillJson(route, 200, {
        ok: true,
        user: {
          userId: authState.userId,
          displayName: authState.userId === USER_ID
            ? "Project Context Test User"
            : "Second Project Context User",
          email: `${authState.userId || "signed-out"}@example.test`,
          role: "user",
          status: "active",
        },
      });
      return;
    }

    if (projectMatch) {
      const projectId = decodeURIComponent(projectMatch[1]);
      stats.projectGets[projectId] = (stats.projectGets[projectId] ?? 0) + 1;
      const fixture = fixtureById.get(projectId);
      if (!fixture) {
        await fulfillJson(route, 404, { ok: false, detail: "Project not found" });
        return;
      }
      if (fixture.waitForProject) await fixture.waitForProject;
      const status = fixture.projectStatus ?? 200;
      await fulfillJson(
        route,
        status,
        status === 200
          ? { ok: true, project: records.get(projectId)! }
          : {
              ok: false,
              detail: status === 403 ? "Project access denied" : "Project not found",
            },
      ).catch(() => undefined);
      return;
    }

    const workflowMatch = pathname.match(/^\/api\/projects\/([^/]+)\/workflow-state$/);
    if (workflowMatch) {
      const projectId = decodeURIComponent(workflowMatch[1]);
      const fixture = fixtureById.get(projectId);
      stats.workflowGets[projectId] = (stats.workflowGets[projectId] ?? 0) + 1;
      await fulfillJson(route, 200, {
        ok: true,
        workflowState: workflowState(projectId, fixture?.workflowType),
      });
      return;
    }

    if (pathname === "/api/data/active-identity") {
      const projectId = url.searchParams.get("project_id") ?? "";
      stats.identityGets[projectId] = (stats.identityGets[projectId] ?? 0) + 1;
      await fulfillJson(route, 200, activeIdentity(projectId));
      return;
    }

    if (pathname === "/api/data/get_sample") {
      const projectId = url.searchParams.get("project_id") ?? "";
      stats.sampleGets[projectId] = (stats.sampleGets[projectId] ?? 0) + 1;
      await fulfillJson(route, 200, {
        ok: true,
        headers: ["predictor_a", "bad_flag"],
        rows: [
          { predictor_a: 1, bad_flag: 0 },
          { predictor_a: 2, bad_flag: 1 },
        ],
        target: "bad_flag",
        selected_columns: ["predictor_a"],
        registered_row_count: 2,
        dataset_id: DATASET_ID,
        dataset_version_id: VERSION_ID,
      });
      return;
    }

    if (pathname === "/api/notifications/unread-count") {
      await fulfillJson(route, 200, { ok: true, count: 0 });
      return;
    }

    // Downstream Data Acquisition reads are deliberately empty. They are not
    // project authority and may not turn hydration into a write operation.
    await fulfillJson(route, 200, {
      ok: true,
      count: 0,
      items: [],
      datasets: [],
      versions: [],
      rows: [],
      headers: [],
      notifications: [],
      findings: [],
      partitions: [],
    });
  });

  return stats;
}

function currentProjectSection(page: Page) {
  return page.locator("section").filter({ hasText: "Current Project" }).first();
}

function activationMutations(stats: RequestStats) {
  return stats.nonGetRequests.filter(({ pathname }) => (
    pathname === "/api/data/active-identity"
    || /\/activate(?:\/|$)/.test(pathname)
  ));
}

function partitionMutations(stats: RequestStats) {
  return stats.nonGetRequests.filter(({ pathname }) => /analysis-partition/i.test(pathname));
}

async function expectReadyProject(
  page: Page,
  projectId: string,
  projectName: string,
) {
  await expect(page).toHaveURL(new RegExp(`/projects/${projectId}/step01`));
  await expect(page.getByTestId("project-context-gate")).toHaveCount(0);
  await expect(page.getByTestId("atlas-breadcrumb")).toHaveAttribute(
    "data-breadcrumb",
    new RegExp(projectName),
  );
  await expect(currentProjectSection(page)).toContainText(projectName);
  await expect(page.getByTestId("atlas-guide-project-context")).toContainText(projectName);
  await expect(page.locator("body")).not.toContainText("Untitled ATLAS Project");
}

test.describe("Project-scoped authoritative frontend hydration", () => {
  test("a configured Credit Risk Studio project hydrates as predictive modeling", async ({ page }) => {
    const projectId = "project-context-credit-risk";
    const projectName = "HELOC Credit Risk Fixture";
    await installProjectContextLifecycleProbe(page);
    const stats = await installProjectAuthorityMocks(page, [{
      projectId,
      projectName,
      workflowType: "credit-risk-studio",
    }]);

    await page.goto(`/projects/${projectId}/step00`);
    await expect(page.getByTestId("model-identity-card")).toBeVisible();
    await expect(page.getByTestId("project-context-gate")).toHaveCount(0);
    await expect(page.getByTestId("atlas-breadcrumb")).toHaveAttribute(
      "data-project-context-status",
      "ready",
    );
    await expect(page.locator("body")).not.toContainText("Project context contradictory");
    await expect(currentProjectSection(page)).toContainText(projectName);

    const settledProjectGets = stats.projectGets[projectId] ?? 0;
    await page.waitForTimeout(1_500);

    const lifecycle = await page.evaluate(
      () => (window as any).__atlasProjectContextLifecycle,
    );
    expect(lifecycle.providerStatuses).toEqual(["resolving", "ready"]);
    expect(lifecycle.mountCount).toBe(1);
    expect(lifecycle.unmountCount).toBe(0);
    expect(settledProjectGets).toBeGreaterThan(0);
    expect(stats.projectGets[projectId]).toBe(settledProjectGets);
    expect(stats.workflowGets[projectId]).toBe(1);
    expect(stats.identityGets[projectId]).toBe(1);
    expect(stats.nonGetRequests).toEqual([]);
  });

  test("the real Project Context composition hydrates once and remains mounted", async ({ page }) => {
    const projectId = "project-context-stable";
    const projectName = "Stable Project Context";
    await installProjectContextLifecycleProbe(page);
    const stats = await installProjectAuthorityMocks(
      page,
      [{ projectId, projectName }],
      undefined,
      { userId: USER_ID },
      {
        projectName: "POISONED OTHER PROJECT",
        modelId: "poisoned-model-id",
        businessObjective: "",
        intendedModelUse: "",
        targetDefinition: "",
        populationDefinition: "",
        observationWindow: "",
        performanceWindow: "",
      },
    );

    await page.goto(`/projects/${projectId}/step00`);
    await expect(page.getByTestId("model-identity-card")).toBeVisible();
    await expect(page.getByTestId("project-context-gate")).toHaveCount(0);
    await page.waitForTimeout(1_500);

    const settledRequests = {
      project: stats.projectGets[projectId] ?? 0,
      workflow: stats.workflowGets[projectId] ?? 0,
      identity: stats.identityGets[projectId] ?? 0,
    };
    await page.waitForTimeout(1_500);

    const lifecycle = await page.evaluate(
      () => (window as any).__atlasProjectContextLifecycle,
    );
    expect(lifecycle).toEqual({
      mountCount: 1,
      unmountCount: 0,
      eventDispatchCount: 0,
      hydrationStartCount: 1,
      hydrationCompleteCount: 1,
      providerStatuses: ["resolving", "ready"],
      lastEventDetail: null,
    });
    expect(settledRequests.project).toBeGreaterThan(0);
    expect(stats.projectGets[projectId]).toBe(settledRequests.project);
    expect(stats.workflowGets[projectId]).toBe(1);
    expect(stats.identityGets[projectId]).toBe(1);
    expect(stats.nonGetRequests).toEqual([]);
    await expect(page.getByTestId("atlas-breadcrumb")).toHaveAttribute(
      "data-breadcrumb",
      new RegExp(projectName),
    );
    await expect(currentProjectSection(page)).toContainText(projectName);
    const guideProject = page.getByTestId("atlas-guide-project-context");
    const atlasGuide = page.locator("aside").filter({ hasText: "Atlas Guide Recommendation" }).first();
    await expect(guideProject).toContainText(projectName);
    await expect(atlasGuide).toContainText(`model-${projectId}`);
    await expect(atlasGuide).toContainText("6 of 6 required narrative inputs");
    await expect(atlasGuide).not.toContainText("POISONED OTHER PROJECT");
    await expect(atlasGuide).not.toContainText("poisoned-model-id");
    await expect(page.locator("body")).not.toContainText("Untitled ATLAS Project");
  });

  test("one acknowledged user save refreshes metadata in place without rehydrating identity", async ({ page }) => {
    const projectId = "project-context-save";
    const originalName = "Project Context Save Fixture";
    const savedName = "Project Context Saved Once";
    const savedObjective = "Use one acknowledged metadata write to prove governed narrative updates remain nonblocking.";
    await installProjectContextLifecycleProbe(page);
    const stats = await installProjectAuthorityMocks(page, [{
      projectId,
      projectName: originalName,
      allowProjectMetadataWrites: true,
    }]);

    await page.goto(`/projects/${projectId}/step00`);
    const card = page.getByTestId("model-identity-card");
    await expect(card).toBeVisible();
    const projectNameInput = card.locator("input").nth(1);
    await expect(projectNameInput).toHaveValue(originalName);
    const authorityBeforeSave = {
      workflow: stats.workflowGets[projectId] ?? 0,
      identity: stats.identityGets[projectId] ?? 0,
    };

    await projectNameInput.fill(savedName);
    const businessObjective = page.locator('textarea[placeholder^="What decision or business process"]');
    await businessObjective.fill(savedObjective);
    const status = page.getByTestId("project-context-save-status");
    await expect.poll(() => stats.projectPuts.length).toBe(1);
    await expect(status).toHaveAttribute("data-save-status", "saved");
    await expect(status).toContainText("Saved to ATLAS database");
    await expect(card.locator("input").nth(1)).toHaveValue(savedName);
    await expect(businessObjective).toHaveValue(savedObjective);
    await expect(page.getByTestId("atlas-breadcrumb")).toHaveAttribute(
      "data-breadcrumb",
      new RegExp(savedName),
    );
    await expect(currentProjectSection(page)).toContainText(savedName);
    await expect(page.getByTestId("atlas-guide-project-context")).toContainText(savedName);
    await expect(page.locator("fieldset[data-metadata-refresh-status]")).toHaveAttribute(
      "data-metadata-refresh-status",
      "saved",
    );
    const projectGetsAfterAcknowledgement = stats.projectGets[projectId] ?? 0;
    await page.waitForTimeout(1_500);

    const lifecycle = await page.evaluate(
      () => (window as any).__atlasProjectContextLifecycle,
    );
    expect(lifecycle).toMatchObject({
      mountCount: 1,
      unmountCount: 0,
      eventDispatchCount: 1,
      hydrationStartCount: 1,
      hydrationCompleteCount: 1,
      providerStatuses: ["resolving", "ready"],
    });
    expect(lifecycle.lastEventDetail).toMatchObject({
      project_id: projectId,
      project_revision: stats.projectPuts[0].revision,
      request_id: expect.stringMatching(
        new RegExp(`^project-context-save:${projectId}:\\d{10,}-[a-z0-9]+:\\d+$`),
      ),
      changed_fields: ["businessObjective", "projectName"],
      source: "user_save",
      saved_at: expect.any(String),
    });
    expect(lifecycle.lastEventDetail).not.toHaveProperty("projectContext");
    expect(stats.projectPuts).toHaveLength(1);
    expect(stats.projectPuts[0]).toMatchObject({ projectId, projectName: savedName });
    expect(stats.projectPuts[0].revision).toMatch(/^\d{10,}-[a-z0-9]+$/);
    expect(stats.workflowGets[projectId]).toBe(authorityBeforeSave.workflow);
    expect(stats.identityGets[projectId]).toBe(authorityBeforeSave.identity);
    expect(stats.projectGets[projectId]).toBe(projectGetsAfterAcknowledgement);
    expect(activationMutations(stats)).toEqual([]);
    expect(partitionMutations(stats)).toEqual([]);
    expect(stats.nonGetRequests).toEqual([]);

    const workflowGetsBeforeNavigation = stats.workflowGets[projectId] ?? 0;
    await page.getByRole("link", { name: "Data Acquisition", exact: true }).click();
    await expect(page).toHaveURL(new RegExp(`/projects/${projectId}/step01`));
    await expect(page.getByTestId("project-context-gate")).toHaveCount(0);
    await page.goBack();
    await expect(page).toHaveURL(new RegExp(`/projects/${projectId}/step00`));
    await expect(page.getByTestId("model-identity-card")).toBeVisible();
    await expect(page.getByTestId("model-identity-card").locator("input").nth(1)).toHaveValue(savedName);
    await page.goForward();
    await expect(page).toHaveURL(new RegExp(`/projects/${projectId}/step01`));
    expect(stats.workflowGets[projectId]).toBe(workflowGetsBeforeNavigation);
    const lifecycleAfterNavigation = await page.evaluate(
      () => (window as any).__atlasProjectContextLifecycle,
    );
    expect(lifecycleAfterNavigation.providerStatuses).toEqual(["resolving", "ready"]);
    expect(lifecycleAfterNavigation.hydrationStartCount).toBe(1);
    expect(lifecycleAfterNavigation.eventDispatchCount).toBe(1);
  });

  test("a newer user-scoped draft survives immediate SPA navigation before the debounce", async ({ page }) => {
    const projectId = "project-context-fast-navigation";
    const projectName = "Fast Navigation Draft Fixture";
    const draft = "This newer unsaved objective must survive an immediate sidebar navigation.";
    const stats = await installProjectAuthorityMocks(page, [{ projectId, projectName }]);

    await page.goto(`/projects/${projectId}/step00`);
    const objective = page.locator('textarea[placeholder^="What decision or business process"]');
    await expect(objective).toBeVisible();
    await objective.fill(draft);
    await page.getByRole("link", { name: "Data Acquisition", exact: true }).click();
    await expect(page).toHaveURL(new RegExp(`/projects/${projectId}/step01`));

    await page.goBack();
    await expect(page).toHaveURL(new RegExp(`/projects/${projectId}/step00`));
    const restored = page.locator('textarea[placeholder^="What decision or business process"]');
    await expect(restored).toHaveValue(draft);
    await expect(page.getByTestId("project-context-save-status")).toHaveAttribute(
      "data-save-status",
      /unsaved|saving|failed|offline/,
    );
    expect(activationMutations(stats)).toEqual([]);
    expect(partitionMutations(stats)).toEqual([]);
  });

  test("editing and reverting before the debounce clears the draft and never writes", async ({ page }) => {
    const projectId = "project-context-revert-before-debounce";
    const projectName = "Revert Before Debounce Fixture";
    const transientObjective = "This transient edit must never become a durable Project Context revision.";
    await installProjectContextLifecycleProbe(page);
    await installDraftCacheProbe(page, projectId);
    const stats = await installProjectAuthorityMocks(page, [{
      projectId,
      projectName,
      allowProjectMetadataWrites: true,
    }]);

    await page.goto(`/projects/${projectId}/step00`);
    const objective = page.locator('textarea[placeholder^="What decision or business process"]');
    await expect(objective).toBeVisible();
    const originalObjective = await objective.inputValue();

    await objective.fill(transientObjective);
    await expect.poll(
      async () => (await readProjectContextDraft(page, projectId))?.context?.businessObjective,
      { timeout: 500, intervals: [10, 20, 50] },
    ).toBe(transientObjective);
    await objective.fill(originalObjective);

    await expect.poll(
      async () => readProjectContextDraft(page, projectId),
      { timeout: 500, intervals: [10, 20, 50] },
    ).toBeNull();
    await page.waitForTimeout(1_000);
    expect(stats.projectPuts).toEqual([]);
    await expect(objective).toHaveValue(originalObjective);

    await page.getByRole("link", { name: "Data Acquisition", exact: true }).click();
    await expect(page).toHaveURL(new RegExp(`/projects/${projectId}/step01`));
    await page.goBack();
    await expect(page).toHaveURL(new RegExp(`/projects/${projectId}/step00`));
    await expect(
      page.locator('textarea[placeholder^="What decision or business process"]'),
    ).toHaveValue(originalObjective);
    expect(await readProjectContextDraft(page, projectId)).toBeNull();
    expect(stats.projectPuts).toEqual([]);
    expect(activationMutations(stats)).toEqual([]);
    expect(partitionMutations(stats)).toEqual([]);

    const lifecycle = await page.evaluate(
      () => (window as any).__atlasProjectContextLifecycle,
    );
    expect(lifecycle).toMatchObject({
      mountCount: 1,
      unmountCount: 0,
      eventDispatchCount: 0,
      hydrationStartCount: 1,
      hydrationCompleteCount: 1,
      providerStatuses: ["resolving", "ready"],
    });
  });

  test("a newer edit waits for a delayed acknowledgement and is saved next without losing its draft", async ({ page }) => {
    const projectId = "project-context-serialized-newer-edit";
    const projectName = "Serialized Newer Edit Fixture";
    const firstObjective = "First durable objective while its acknowledgement is deliberately delayed.";
    const latestObjective = "Latest objective entered while the first durable save is still awaiting acknowledgement.";
    const firstAcknowledgement = deferredAcknowledgement();
    const secondAcknowledgement = deferredAcknowledgement();
    await installProjectContextLifecycleProbe(page);
    await installDraftCacheProbe(page, projectId);
    const stats = await installProjectAuthorityMocks(page, [{
      projectId,
      projectName,
      allowProjectMetadataWrites: true,
      waitForProjectPut: ({ putNumber }) => {
        if (putNumber === 1) return firstAcknowledgement.wait;
        if (putNumber === 2) return secondAcknowledgement.wait;
        return Promise.resolve();
      },
    }]);

    await page.goto(`/projects/${projectId}/step00`);
    const objective = page.locator('textarea[placeholder^="What decision or business process"]');
    await expect(objective).toBeVisible();
    await objective.fill(firstObjective);
    await expect.poll(() => stats.projectPuts.length).toBe(1);
    expect(stats.projectPuts[0].projectContext.businessObjective).toBe(firstObjective);

    await objective.fill(latestObjective);
    await expect.poll(
      async () => (await readProjectContextDraft(page, projectId))?.context?.businessObjective,
      { timeout: 500, intervals: [10, 20, 50] },
    ).toBe(latestObjective);
    await page.waitForTimeout(1_000);
    expect(stats.projectPuts).toHaveLength(1);
    await expect.poll(
      async () => (await readProjectContextDraft(page, projectId))?.context?.businessObjective,
    ).toBe(latestObjective);
    const operationsBeforeRelease = await readDraftCacheOperations(page);
    const latestDraftOperationIndex = operationsBeforeRelease.findIndex((operation) => {
      if (operation.operation !== "set" || !operation.value) return false;
      return JSON.parse(operation.value)?.context?.businessObjective === latestObjective;
    });
    expect(latestDraftOperationIndex).toBeGreaterThanOrEqual(0);

    firstAcknowledgement.release();
    await expect.poll(() => stats.projectPuts.length).toBe(2);
    expect(stats.projectPuts[1].projectContext.businessObjective).toBe(latestObjective);
    await expect(objective).toHaveValue(latestObjective);
    await expect.poll(
      async () => (await readProjectContextDraft(page, projectId))?.context?.businessObjective,
    ).toBe(latestObjective);
    const operationsBeforeLatestAcknowledgement = await readDraftCacheOperations(page);
    expect(
      operationsBeforeLatestAcknowledgement
        .slice(latestDraftOperationIndex + 1)
        .some((operation) => operation.operation === "remove"),
    ).toBe(false);

    secondAcknowledgement.release();
    await expect(page.getByTestId("project-context-save-status")).toHaveAttribute(
      "data-save-status",
      "saved",
    );
    await expect.poll(async () => readProjectContextDraft(page, projectId)).toBeNull();
    await expect(objective).toHaveValue(latestObjective);
    await page.waitForTimeout(1_000);
    expect(stats.projectPuts).toHaveLength(2);

    const backendObjective = await page.evaluate(async (id) => {
      const response = await fetch(`/api/projects/${encodeURIComponent(id)}`, {
        credentials: "include",
      });
      const payload = await response.json();
      return payload.project.metadata.projectContext.businessObjective;
    }, projectId);
    expect(backendObjective).toBe(latestObjective);
    const lifecycle = await page.evaluate(
      () => (window as any).__atlasProjectContextLifecycle,
    );
    expect(lifecycle).toMatchObject({
      mountCount: 1,
      unmountCount: 0,
      hydrationStartCount: 1,
      hydrationCompleteCount: 1,
      providerStatuses: ["resolving", "ready"],
    });
    expect(activationMutations(stats)).toEqual([]);
    expect(partitionMutations(stats)).toEqual([]);
    expect(stats.nonGetRequests).toEqual([]);
  });

  test("reverting while a save acknowledgement is delayed serializes a restoring save", async ({ page }) => {
    const projectId = "project-context-serialized-revert";
    const projectName = "Serialized Revert Fixture";
    const firstObjective = "A temporary objective whose delayed save must be followed by an explicit revert.";
    const firstAcknowledgement = deferredAcknowledgement();
    const secondAcknowledgement = deferredAcknowledgement();
    await installProjectContextLifecycleProbe(page);
    await installDraftCacheProbe(page, projectId);
    const stats = await installProjectAuthorityMocks(page, [{
      projectId,
      projectName,
      allowProjectMetadataWrites: true,
      waitForProjectPut: ({ putNumber }) => {
        if (putNumber === 1) return firstAcknowledgement.wait;
        if (putNumber === 2) return secondAcknowledgement.wait;
        return Promise.resolve();
      },
    }]);

    await page.goto(`/projects/${projectId}/step00`);
    const objective = page.locator('textarea[placeholder^="What decision or business process"]');
    await expect(objective).toBeVisible();
    const originalObjective = await objective.inputValue();
    await objective.fill(firstObjective);
    await expect.poll(() => stats.projectPuts.length).toBe(1);
    expect(stats.projectPuts[0].projectContext.businessObjective).toBe(firstObjective);

    await objective.fill(originalObjective);
    await expect.poll(
      async () => (await readProjectContextDraft(page, projectId))?.context?.businessObjective,
      { timeout: 500, intervals: [10, 20, 50] },
    ).toBe(originalObjective);
    await page.waitForTimeout(1_000);
    expect(stats.projectPuts).toHaveLength(1);
    await expect.poll(
      async () => (await readProjectContextDraft(page, projectId))?.context?.businessObjective,
    ).toBe(originalObjective);
    const operationsBeforeRelease = await readDraftCacheOperations(page);
    const revertDraftOperationIndex = operationsBeforeRelease.findIndex((operation) => {
      if (operation.operation !== "set" || !operation.value) return false;
      return JSON.parse(operation.value)?.context?.businessObjective === originalObjective;
    });
    expect(revertDraftOperationIndex).toBeGreaterThanOrEqual(0);

    firstAcknowledgement.release();
    await expect.poll(() => stats.projectPuts.length).toBe(2);
    expect(stats.projectPuts[1].projectContext.businessObjective).toBe(originalObjective);
    await expect(objective).toHaveValue(originalObjective);
    await expect.poll(
      async () => (await readProjectContextDraft(page, projectId))?.context?.businessObjective,
    ).toBe(originalObjective);
    const operationsBeforeRevertAcknowledgement = await readDraftCacheOperations(page);
    expect(
      operationsBeforeRevertAcknowledgement
        .slice(revertDraftOperationIndex + 1)
        .some((operation) => operation.operation === "remove"),
    ).toBe(false);

    secondAcknowledgement.release();
    await expect(page.getByTestId("project-context-save-status")).toHaveAttribute(
      "data-save-status",
      "saved",
    );
    await expect.poll(async () => readProjectContextDraft(page, projectId)).toBeNull();
    await expect(objective).toHaveValue(originalObjective);
    await page.waitForTimeout(1_000);
    expect(stats.projectPuts).toHaveLength(2);

    const backendObjective = await page.evaluate(async (id) => {
      const response = await fetch(`/api/projects/${encodeURIComponent(id)}`, {
        credentials: "include",
      });
      const payload = await response.json();
      return payload.project.metadata.projectContext.businessObjective;
    }, projectId);
    expect(backendObjective).toBe(originalObjective);
    const lifecycle = await page.evaluate(
      () => (window as any).__atlasProjectContextLifecycle,
    );
    expect(lifecycle).toMatchObject({
      mountCount: 1,
      unmountCount: 0,
      hydrationStartCount: 1,
      hydrationCompleteCount: 1,
      providerStatuses: ["resolving", "ready"],
    });
    expect(activationMutations(stats)).toEqual([]);
    expect(partitionMutations(stats)).toEqual([]);
    expect(stats.nonGetRequests).toEqual([]);
  });

  test("an already-complete bottom CTA recovers its exact committed revision and advances", async ({ page }) => {
    const projectId = "project-context-complete-ambiguous-ack";
    const projectName = "Complete Ambiguous Acknowledgement Fixture";
    await installProjectContextLifecycleProbe(page);
    await installDraftCacheProbe(page, projectId);
    const stats = await installProjectAuthorityMocks(page, [{
      projectId,
      projectName,
      allowProjectMetadataWrites: true,
      allowProjectCompletionWrites: true,
      ambiguousProjectContextAckOnce: true,
      projectContextOverrides: {
        completionStatus: "complete",
        completedAt: "2026-08-01T17:45:43.490Z",
        completedBy: USER_ID,
        updatedBy: "",
      },
    }]);

    await page.goto(`/projects/${projectId}/step00`);
    const continueButton = page.getByRole("button", {
      name: "Continue to Data Acquisition",
      exact: true,
    });
    await expect(continueButton).toBeEnabled();
    await continueButton.click();

    await expect(page).toHaveURL(new RegExp(`/projects/${projectId}/step01`));
    await expect(page.getByTestId("project-context-gate")).toHaveCount(0);
    await expect(page.locator("body")).not.toContainText("This project was updated elsewhere");
    expect(stats.projectPuts).toHaveLength(1);
    expect(stats.projectPuts[0].projectContext).toMatchObject({
      completionStatus: "complete",
      updatedBy: USER_ID,
    });
    expect(activationMutations(stats)).toEqual([]);
    expect(partitionMutations(stats)).toEqual([]);
    await expect.poll(async () => readProjectContextDraft(page, projectId)).toBeNull();

    const lifecycle = await page.evaluate(
      () => (window as any).__atlasProjectContextLifecycle,
    );
    expect(lifecycle).toMatchObject({
      mountCount: 1,
      eventDispatchCount: 1,
      hydrationStartCount: 1,
      hydrationCompleteCount: 1,
      providerStatuses: ["resolving", "ready"],
    });
    // The assertion runs immediately after the in-app route transition, so
    // React's Step 00 cleanup can be observed just before or just after it.
    // Either zero or one cleanup is valid; a lifecycle loop would exceed one.
    expect(lifecycle.unmountCount).toBeLessThanOrEqual(1);
  });

  test("Generate, Accept Summary, and Continue survive backend JSON key sorting", async ({ page }) => {
    const projectId = "project-context-accepted-summary-ordering";
    const projectName = "Accepted Summary Ordering Fixture";
    await installProjectContextLifecycleProbe(page);
    await installDraftCacheProbe(page, projectId);
    const completedAt = "2026-08-01T17:45:43.490Z";
    const stats = await installProjectAuthorityMocks(page, [{
      projectId,
      projectName,
      allowProjectMetadataWrites: true,
      allowProjectCompletionWrites: true,
      sortStoredJsonKeys: true,
      projectContextOverrides: {
        completionStatus: "complete",
        completedAt,
        completedBy: USER_ID,
        updatedBy: USER_ID,
        modelingMissionSummary: "",
        acceptedAiDrafts: [],
      },
    }]);

    await page.goto(`/projects/${projectId}/step01`);
    await expectReadyProject(page, projectId, projectName);
    const projectContextLink = page.getByRole("link", {
      name: "Project Context",
      exact: true,
    });
    await expect(projectContextLink).toHaveCount(1);
    await projectContextLink.click();
    await expect(page).toHaveURL(new RegExp(`/projects/${projectId}/step00`));
    await expect(page.getByTestId("project-context-save-status")).toHaveAttribute(
      "data-save-status",
      "saved",
    );
    expect(stats.projectPuts).toHaveLength(0);

    const generateButton = page.getByRole("button", {
      name: "Generate Modeling Mission Summary",
      exact: true,
    });
    await expect(generateButton).toHaveCount(1);
    await generateButton.click();
    const draft = page.getByLabel("Editable AI Modeling Mission Summary draft", {
      exact: true,
    });
    await expect(draft).toHaveCount(1);
    const generatedSummary = await draft.inputValue();
    expect(generatedSummary.length).toBeGreaterThan(100);
    expect(stats.projectPuts).toHaveLength(0);

    const acceptButton = page.getByRole("button", {
      name: "Accept Summary",
      exact: true,
    });
    await expect(acceptButton).toHaveCount(1);
    await acceptButton.click();
    await expect.poll(() => stats.projectPuts.length).toBe(1);
    await expect(page.getByTestId("project-context-save-status")).toHaveAttribute(
      "data-save-status",
      "saved",
    );
    expect(stats.projectPuts[0].projectContext).toMatchObject({
      modelingMissionSummary: generatedSummary,
      completionStatus: "complete",
      completedAt,
      updatedBy: USER_ID,
      acceptedAiDrafts: [expect.objectContaining({
        field: "modelingMissionSummary",
        action: "Draft from current project context",
        text: generatedSummary,
        acceptedAt: expect.any(String),
        acceptedBy: USER_ID,
      })],
    });
    await expect(page.locator("body")).not.toContainText("This project was updated elsewhere");
    await expect.poll(async () => readProjectContextDraft(page, projectId)).toBeNull();

    const continueButton = page.getByRole("button", {
      name: "Continue to Data Acquisition",
      exact: true,
    });
    await expect(continueButton).toHaveCount(1);
    await continueButton.click();
    await expect(page).toHaveURL(new RegExp(`/projects/${projectId}/step01`));
    expect(stats.projectPuts).toHaveLength(1);
    expect(activationMutations(stats)).toEqual([]);
    expect(partitionMutations(stats)).toEqual([]);
  });

  test("governed completion waits for its exact serialized acknowledgement before evidence and navigation", async ({ page }) => {
    const projectId = "project-context-serialized-completion";
    const projectName = "Serialized Completion Fixture";
    const editedObjective = "This governed objective is completed only after its exact serialized revision is durable.";
    const firstAcknowledgement = deferredAcknowledgement();
    const completionAcknowledgement = deferredAcknowledgement();
    await installProjectContextLifecycleProbe(page);
    await installDraftCacheProbe(page, projectId);
    const stats = await installProjectAuthorityMocks(page, [{
      projectId,
      projectName,
      allowProjectMetadataWrites: true,
      allowProjectCompletionWrites: true,
      waitForProjectPut: ({ putNumber }) => {
        if (putNumber === 1) return firstAcknowledgement.wait;
        if (putNumber === 2) return completionAcknowledgement.wait;
        return Promise.resolve();
      },
    }]);

    await page.goto(`/projects/${projectId}/step00`);
    const objective = page.locator('textarea[placeholder^="What decision or business process"]');
    const continueButton = page.getByRole("button", {
      name: "Continue to Data Acquisition",
      exact: true,
    });
    await expect(objective).toBeVisible();
    await expect(continueButton).toBeEnabled();

    await objective.fill(editedObjective);
    await expect.poll(() => stats.projectPuts.length).toBe(1);
    expect(stats.projectPuts[0].projectContext.businessObjective).toBe(editedObjective);
    expect(stats.projectPuts[0].projectContext.completionStatus).not.toBe("complete");

    await continueButton.click();
    await expect.poll(
      async () => (await readProjectContextDraft(page, projectId))?.context?.completionStatus,
      { timeout: 500, intervals: [10, 20, 50] },
    ).toBe("complete");
    await page.waitForTimeout(1_000);
    expect(stats.projectPuts).toHaveLength(1);
    expect(stats.completionSideEffects).toEqual([]);
    await expect(page).toHaveURL(new RegExp(`/projects/${projectId}/step00`));
    await expect(page.locator("body")).not.toContainText(
      "Project Context could not be saved",
    );

    firstAcknowledgement.release();
    await expect.poll(() => stats.projectPuts.length).toBe(2);
    const completionContext = stats.projectPuts[1].projectContext;
    expect(completionContext).toMatchObject({
      businessObjective: editedObjective,
      completionStatus: "complete",
      completedAt: expect.any(String),
    });
    expect(String(completionContext.completedAt)).not.toBe("");
    await page.waitForTimeout(500);
    expect(stats.completionSideEffects).toEqual([]);
    await expect(page).toHaveURL(new RegExp(`/projects/${projectId}/step00`));
    await expect.poll(
      async () => (await readProjectContextDraft(page, projectId))?.context?.completionStatus,
    ).toBe("complete");
    await expect(page.locator("body")).not.toContainText(
      "Project Context could not be saved",
    );

    completionAcknowledgement.release();
    await expect(page).toHaveURL(new RegExp(`/projects/${projectId}/step01`));
    await expect.poll(
      () => stats.completionSideEffects.some(({ pathname }) => pathname === "/api/evidence"),
    ).toBe(true);
    await expect.poll(
      () => stats.completionSideEffects.some(({ pathname }) => (
        pathname === `/api/projects/${projectId}/evidence`
      )),
    ).toBe(true);
    await expect.poll(
      () => stats.completionSideEffects.some(({ pathname }) => (
        pathname === `/api/projects/${projectId}/decisions`
      )),
    ).toBe(true);
    await expect.poll(async () => readProjectContextDraft(page, projectId)).toBeNull();
    expect(stats.projectPuts).toHaveLength(2);
    expect(stats.projectPuts[1].projectContext.businessObjective).toBe(editedObjective);
    expect(stats.projectPuts[1].projectContext.completionStatus).toBe("complete");
    expect(activationMutations(stats)).toEqual([]);
    expect(partitionMutations(stats)).toEqual([]);
    expect(stats.nonGetRequests).toEqual([]);

    const lifecycle = await page.evaluate(
      () => (window as any).__atlasProjectContextLifecycle,
    );
    expect(lifecycle).toMatchObject({
      mountCount: 1,
      hydrationStartCount: 1,
      hydrationCompleteCount: 1,
      providerStatuses: ["resolving", "ready"],
    });
    expect(lifecycle.unmountCount).toBeLessThanOrEqual(1);
  });

  test("a fresh direct link blocks Data Acquisition until exact hydration and survives refresh", async ({ page }) => {
    let releaseProject = () => undefined;
    const projectRelease = new Promise<void>((resolve) => {
      releaseProject = resolve;
    });
    let markRequested = () => undefined;
    const requested = new Promise<void>((resolve) => {
      markRequested = resolve;
    });
    const fixture: ProjectFixture = {
      projectId: "project-a",
      projectName: "Authoritative Project A",
      waitForProject: projectRelease.then(() => undefined),
    };
    const stats = await installProjectAuthorityMocks(page, [fixture]);

    page.on("request", (request) => {
      if (new URL(request.url()).pathname === "/api/projects/project-a") {
        markRequested();
      }
    });

    await page.goto("/projects/project-a/step01?source=library#target-setup");
    await requested;
    const gate = page.getByTestId("project-context-gate");
    await expect(gate).toHaveAttribute("data-project-context-status", "resolving");
    await expect(gate).toContainText("Loading project context...");
    await expect(page.getByTestId("data-acquisition-target-setup")).toHaveCount(0);
    await expect(page.locator("body")).not.toContainText("Untitled ATLAS Project");
    await expect(page.locator("body")).not.toContainText("Project: Not defined");
    await expect(page.locator("body")).not.toContainText("Load failed");
    expect(stats.nonGetRequests).toEqual([]);

    releaseProject();
    await expectReadyProject(page, "project-a", "Authoritative Project A");
    await expect(page).toHaveURL(
      /\/projects\/project-a\/step01\?source=library#target-setup$/,
    );
    await expect(page.getByTestId("data-acquisition-target-setup")).toBeVisible();
    expect(stats.projectGets["project-a"]).toBeGreaterThanOrEqual(1);
    expect(stats.workflowGets["project-a"]).toBeGreaterThanOrEqual(1);
    expect(stats.identityGets["project-a"]).toBeGreaterThanOrEqual(1);
    expect(stats.sampleGets["project-a"]).toBeGreaterThanOrEqual(1);
    expect(activationMutations(stats)).toEqual([]);
    expect(partitionMutations(stats)).toEqual([]);

    const projectGetsBeforeReload = stats.projectGets["project-a"];
    const workflowGetsBeforeReload = stats.workflowGets["project-a"];

    await page.reload();
    await expectReadyProject(page, "project-a", "Authoritative Project A");
    await expect(page.getByTestId("data-acquisition-target-setup")).toBeVisible();
    expect(stats.projectGets["project-a"]).toBeGreaterThan(projectGetsBeforeReload);
    expect(stats.workflowGets["project-a"]).toBeGreaterThan(workflowGetsBeforeReload);
    expect(activationMutations(stats)).toEqual([]);
    expect(partitionMutations(stats)).toEqual([]);
  });

  test("an unauthorized scoped URL fails closed with a precise 403 state", async ({ page }) => {
    const stats = await installProjectAuthorityMocks(page, [{
      projectId: "project-forbidden",
      projectName: "Invisible Project",
      projectStatus: 403,
    }]);
    await page.goto("/projects/project-forbidden/step01");

    const gate = page.getByTestId("project-context-gate");
    await expect(gate).toHaveAttribute("data-project-context-status", "unauthorized");
    await expect(gate).toContainText("Project unauthorized");
    await expect(gate).toContainText("do not have permission");
    await expect(gate).toHaveAttribute("data-route-project-id", "project-forbidden");
    await expect(page.getByTestId("data-acquisition-target-setup")).toHaveCount(0);
    expect(stats.workflowGets["project-forbidden"] ?? 0).toBe(0);
    expect(stats.identityGets["project-forbidden"] ?? 0).toBe(0);
    expect(stats.nonGetRequests).toEqual([]);
  });

  test("a missing scoped URL reports project unavailable without opening a default project", async ({ page }) => {
    const stats = await installProjectAuthorityMocks(page, [{
      projectId: "project-missing",
      projectName: "Missing Project",
      projectStatus: 404,
    }]);
    await page.goto("/projects/project-missing/step01");

    const gate = page.getByTestId("project-context-gate");
    await expect(gate).toHaveAttribute("data-project-context-status", "not_found");
    await expect(gate).toContainText("Project unavailable");
    await expect(gate).toContainText("unavailable or no longer exists");
    await expect(page.locator("body")).not.toContainText("Untitled ATLAS Project");
    await expect(page.getByTestId("data-acquisition-target-setup")).toHaveCount(0);
    expect(stats.nonGetRequests).toEqual([]);
  });

  test("a late Project A response cannot replace ready Project B context", async ({ page }) => {
    let releaseA = () => undefined;
    const waitForA = new Promise<void>((resolve) => {
      releaseA = resolve;
    });
    let markARequested = () => undefined;
    const aRequested = new Promise<void>((resolve) => {
      markARequested = resolve;
    });
    const stats = await installProjectAuthorityMocks(page, [
      { projectId: "project-a", projectName: "Late Project A", waitForProject: waitForA },
      { projectId: "project-b", projectName: "Current Project B" },
    ]);
    page.on("request", (request) => {
      if (new URL(request.url()).pathname === "/api/projects/project-a") {
        markARequested();
      }
    });

    await page.goto("/projects/project-a/step01");
    await aRequested;
    await expect(page.getByTestId("project-context-gate")).toHaveAttribute(
      "data-route-project-id",
      "project-a",
    );

    await page.evaluate(() => {
      history.pushState({}, "", "/projects/project-b/step01");
      window.dispatchEvent(new PopStateEvent("popstate"));
    });
    await expectReadyProject(page, "project-b", "Current Project B");

    releaseA();
    await expect(page.getByTestId("atlas-breadcrumb")).toHaveAttribute(
      "data-breadcrumb",
      /Current Project B/,
    );
    await expect(currentProjectSection(page)).not.toContainText("Late Project A");
    await expect(page.getByTestId("atlas-guide-project-context")).not.toContainText("Late Project A");
    expect(stats.workflowGets["project-a"] ?? 0).toBe(0);
    expect(stats.identityGets["project-a"] ?? 0).toBe(0);
    expect(activationMutations(stats)).toEqual([]);
    expect(partitionMutations(stats)).toEqual([]);

    await page.goBack();
    await expectReadyProject(page, "project-a", "Late Project A");
    await page.goForward();
    await expectReadyProject(page, "project-b", "Current Project B");
    expect(activationMutations(stats)).toEqual([]);
    expect(partitionMutations(stats)).toEqual([]);
  });

  test("Project A and Project B remain isolated across two tabs and refreshes", async ({ context, page }) => {
    const pageB = await context.newPage();
    const fixtures = [
      { projectId: "project-a", projectName: "Isolated Project A" },
      { projectId: "project-b", projectName: "Isolated Project B" },
    ];
    const statsA = await installProjectAuthorityMocks(page, fixtures);
    const statsB = await installProjectAuthorityMocks(pageB, fixtures);

    await Promise.all([
      page.goto("/projects/project-a/step01"),
      pageB.goto("/projects/project-b/step01"),
    ]);
    await expectReadyProject(page, "project-a", "Isolated Project A");
    await expectReadyProject(pageB, "project-b", "Isolated Project B");
    await expect(page.locator("body")).not.toContainText("Isolated Project B");
    await expect(pageB.locator("body")).not.toContainText("Isolated Project A");

    await Promise.all([page.reload(), pageB.reload()]);
    await expectReadyProject(page, "project-a", "Isolated Project A");
    await expectReadyProject(pageB, "project-b", "Isolated Project B");
    expect(statsA.projectGets["project-b"] ?? 0).toBe(0);
    expect(statsB.projectGets["project-a"] ?? 0).toBe(0);
    expect(activationMutations(statsA)).toEqual([]);
    expect(activationMutations(statsB)).toEqual([]);
    expect(partitionMutations(statsA)).toEqual([]);
    expect(partitionMutations(statsB)).toEqual([]);
  });

  test("sign-out and a different sign-in cannot recover the prior user's unsaved Project Context draft", async ({ page }) => {
    const projectId = "project-context-user-isolation";
    const authState = { userId: USER_ID };
    await installProjectAuthorityMocks(
      page,
      [{
        projectId,
        projectName: "User-Isolated Project Context",
        hasStoredProjectContext: false,
      }],
      undefined,
      authState,
    );

    await page.goto(`/projects/${projectId}/step00`);
    const objective = page.locator('textarea[placeholder^="What decision or business process"]');
    await expect(objective).toBeVisible();
    const priorUserDraft = "This unsaved draft belongs only to the first authenticated user.";
    await objective.fill(priorUserDraft);
    await expect(page.getByTestId("project-context-save-status")).toHaveAttribute(
      "data-save-status",
      /failed|offline/,
    );

    await page.getByTitle("Signed in as Project Context Test User").click();
    await page.getByRole("button", { name: "Sign out", exact: true }).click();
    await expect(page).toHaveURL(/\/login/);
    await expect(page.getByRole("heading", { name: /sign in to atlas/i })).toBeVisible();

    authState.userId = "project-context-second-user";
    await page.goto(`/projects/${projectId}/step00`);
    await expect(page.getByTestId("model-identity-card")).toBeVisible();
    const secondUserObjective = page.locator('textarea[placeholder^="What decision or business process"]');
    await expect(secondUserObjective).not.toHaveValue(priorUserDraft);
    await expect(secondUserObjective).toHaveValue("");
    await expect(page.getByTestId("atlas-breadcrumb")).toHaveAttribute(
      "data-breadcrumb",
      /User-Isolated Project Context/,
    );
  });

  test("legacy routes choose only an exact current project or Open Project", async ({ browser }) => {
    const freshContext = await browser.newContext();
    const freshPage = await freshContext.newPage();
    const freshStats = await installProjectAuthorityMocks(freshPage, []);
    await freshPage.goto("/step01?legacy=fresh");
    await expect(freshPage).toHaveURL(/\/projects\/open$/);
    expect(Object.keys(freshStats.projectGets)).toEqual([]);
    expect(freshStats.nonGetRequests).toEqual([]);
    await freshContext.close();

    const exactContext = await browser.newContext();
    const exactPage = await exactContext.newPage();
    const exactStats = await installProjectAuthorityMocks(
      exactPage,
      [{ projectId: "project-exact", projectName: "Exact Legacy Project" }],
      {
        projectId: "project-exact",
        projectName: "Exact Legacy Project",
        projectType: "predictive-modeling",
        workflowId: "predictive-modeling",
      },
    );
    await exactPage.goto("/step01?legacy=exact#target");
    await expect(exactPage).toHaveURL(
      /\/projects\/project-exact\/step01\?legacy=exact#target$/,
    );
    await expectReadyProject(exactPage, "project-exact", "Exact Legacy Project");
    expect(exactStats.projectGets["project-exact"]).toBeGreaterThanOrEqual(1);
    expect(activationMutations(exactStats)).toEqual([]);
    expect(partitionMutations(exactStats)).toEqual([]);
    await exactContext.close();
  });
});
