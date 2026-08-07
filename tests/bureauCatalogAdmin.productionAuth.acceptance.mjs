import { chromium } from "@playwright/test";
import { appendFileSync } from "node:fs";
import { mkdir } from "node:fs/promises";
import path from "node:path";

function argument(name) {
  const index = process.argv.indexOf(name);
  if (index < 0 || !process.argv[index + 1]) throw new Error(`Missing ${name}.`);
  return process.argv[index + 1];
}

function optionalArgument(name) {
  const index = process.argv.indexOf(name);
  return index < 0 ? "" : (process.argv[index + 1] ?? "");
}

const frontendUrl = argument("--frontend-url").replace(/\/$/, "");
const backendUrl = argument("--backend-url").replace(/\/$/, "");
const outputDirectory = path.resolve(argument("--output-directory"));
const browserProfileDirectory = path.resolve(argument("--browser-profile-directory"));
const downloadsDirectory = path.resolve(argument("--downloads-directory"));
const expectedVersionId = argument("--expected-version-id");
const expectedSecondaryVersionId = argument("--expected-secondary-version-id");
const projectAlpha = {
  projectId: argument("--project-alpha-id"),
  datasetId: argument("--project-alpha-dataset-id"),
  datasetVersionId: argument("--project-alpha-dataset-version-id"),
  principal: "synthetic-project-user-alpha",
  profile: "project-user-alpha",
  screenshot: "production-auth-project-alpha-isolation.png",
};
const projectBeta = {
  projectId: argument("--project-beta-id"),
  datasetId: argument("--project-beta-dataset-id"),
  datasetVersionId: argument("--project-beta-dataset-version-id"),
  principal: "synthetic-project-user-beta",
  profile: "project-user-beta",
  screenshot: "production-auth-project-beta-isolation.png",
};
const forbiddenPathFragment = argument("--forbidden-path-fragment").toLowerCase();
const syntheticRunId = optionalArgument("--synthetic-run-id");
const networkViolationFile = optionalArgument("--network-violation-file");
const headed = process.argv.includes("--headed");
const authenticatedReloadAttempts = Number(optionalArgument("--authenticated-reload-attempts") || "10");
const projectReloadAttemptsPerProject = Number(optionalArgument("--project-reload-attempts") || "5");
for (const [label, value] of [
  ["authenticated reload attempts", authenticatedReloadAttempts],
  ["project reload attempts", projectReloadAttemptsPerProject],
]) {
  if (!Number.isSafeInteger(value) || value < 1 || value > 60) {
    throw new Error(`Invalid ${label}.`);
  }
}
const routeUrl = `${frontendUrl}/admin/bureau-catalogs`;
const apiPrefix = `${backendUrl}/api/`;

for (const directory of [outputDirectory, browserProfileDirectory, downloadsDirectory]) {
  await mkdir(directory, { recursive: true });
}

const networkEvidence = {
  fetch_xhr_count: 0,
  isolated_backend_fetch_xhr_count: 0,
  unexpected_fetch_xhr_urls: [],
  websocket_count: 0,
  blocked_request_count: 0,
  live_port_contact_count: 0,
};
const allowedOrigins = new Set([frontendUrl, backendUrl]);

function recordNetworkViolation(kind) {
  if (!networkViolationFile) return;
  appendFileSync(networkViolationFile, `${JSON.stringify({
    schema_version: "1.0",
    classification: "isolated_browser_network_violation",
    kind,
    occurred_at: new Date().toISOString(),
  })}\n`, { encoding: "utf8" });
}

function assertNoSensitiveDetail(text, label) {
  const lowered = text.toLowerCase();
  const forbidden = [
    "restricted_storage_reference",
    "attribute_definitions.jsonl",
    "special_value_definitions.jsonl",
    "catalog_manifest.json",
    forbiddenPathFragment,
  ];
  if (forbidden.some((value) => value && lowered.includes(value))) {
    throw new Error(`${label} exposed restricted catalog or authority detail.`);
  }
  if (/[a-z]:\\[^\r\n]+/i.test(text)) {
    throw new Error(`${label} exposed a physical Windows path.`);
  }
}

function observeNetwork(page, evidence) {
  let sequence = 0;
  let cycle = 1;
  const authResponses = [];
  const catalogRequests = [];
  page.on("request", (request) => {
    const kind = request.resourceType();
    if (kind !== "fetch" && kind !== "xhr") return;
    sequence += 1;
    networkEvidence.fetch_xhr_count += 1;
    const url = request.url();
    if (url.startsWith(apiPrefix)) {
      networkEvidence.isolated_backend_fetch_xhr_count += 1;
    } else {
      networkEvidence.unexpected_fetch_xhr_urls.push(url);
    }
    if (new URL(url).pathname.startsWith("/api/admin/bureau-catalogs")) {
      catalogRequests.push({ cycle, sequence, url });
    }
  });
  page.on("response", (response) => {
    const pathname = new URL(response.url()).pathname;
    if (pathname === "/api/auth/me") {
      sequence += 1;
      authResponses.push({ cycle, sequence, status: response.status() });
    }
  });
  page.on("websocket", () => {
    networkEvidence.websocket_count += 1;
    recordNetworkViolation("websocket_or_hmr");
  });
  evidence.authResponses = authResponses;
  evidence.catalogRequests = catalogRequests;
  evidence.nextCycle = () => {
    cycle += 1;
    return cycle;
  };
}

async function openPersistentContext(label, headers = {}) {
  const profile = path.join(browserProfileDirectory, label);
  const downloads = path.join(downloadsDirectory, label);
  await mkdir(profile, { recursive: true });
  await mkdir(downloads, { recursive: true });
  const context = await chromium.launchPersistentContext(profile, {
    headless: !headed,
    serviceWorkers: "block",
    acceptDownloads: true,
    downloadsPath: downloads,
    viewport: { width: 1440, height: 1000 },
    extraHTTPHeaders: {
      ...(syntheticRunId ? { "X-Synthetic-Run-Id": syntheticRunId } : {}),
      ...headers,
    },
  });
  await context.route("**/*", async (route) => {
    let parsed;
    try {
      parsed = new URL(route.request().url());
    } catch {
      networkEvidence.blocked_request_count += 1;
      recordNetworkViolation("invalid_request_url");
      await route.abort("blockedbyclient");
      return;
    }
    if (parsed.protocol === "http:" || parsed.protocol === "https:") {
      if (parsed.port === "5174" || parsed.port === "8001") {
        networkEvidence.live_port_contact_count += 1;
        networkEvidence.blocked_request_count += 1;
        recordNetworkViolation("live_service_port");
        await route.abort("blockedbyclient");
        return;
      }
      if (!allowedOrigins.has(parsed.origin)) {
        networkEvidence.blocked_request_count += 1;
        recordNetworkViolation("non_isolated_origin");
        await route.abort("blockedbyclient");
        return;
      }
    }
    await route.continue();
  });
  return context;
}

const commonHeaders = {
  "X-Synthetic-Tenant": "synthetic-tenant",
};

function boundedCatalogText(value, label, maxLength = 160) {
  const text = String(value ?? "").trim();
  if (!text || text.length > maxLength || /[\u0000-\u001f\u007f]/.test(text)) {
    throw new Error(`The exact catalog ${label} was missing or invalid.`);
  }
  return text;
}

function escapeRegExp(value) {
  return value.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}

async function selectExactExpectedCatalog(page, versionId) {
  const exactVersionId = boundedCatalogText(versionId, "version identifier", 256);
  const listing = await page.evaluate(async ({ endpoint, expectedId }) => {
    const response = await fetch(endpoint, {
      credentials: "include",
      headers: { Accept: "application/json" },
    });
    const body = await response.json().catch(() => null);
    const catalogs = Array.isArray(body?.catalogs) ? body.catalogs : [];
    return {
      status: response.status,
      ok: body?.ok === true,
      matches: catalogs
        .filter((catalog) => catalog?.catalog_version_id === expectedId)
        .map((catalog) => ({
          catalog_version_id: catalog.catalog_version_id,
          provider_name: catalog.provider_name,
          product_name: catalog.product_name,
          edition: catalog.edition,
          source_release_version: catalog.source_release_version,
        })),
    };
  }, {
    endpoint: `${backendUrl}/api/admin/bureau-catalogs?offset=0&limit=50`,
    expectedId: exactVersionId,
  });

  if (listing.status !== 200 || listing.ok !== true || listing.matches.length !== 1) {
    throw new Error("The entitled inventory did not resolve exactly one expected catalog version.");
  }
  const exactCatalog = listing.matches.find(
    (catalog) => catalog.catalog_version_id === exactVersionId,
  );
  if (!exactCatalog) {
    throw new Error("The exact catalog identity disappeared after inventory resolution.");
  }
  const provider = boundedCatalogText(exactCatalog.provider_name, "provider label");
  const product = boundedCatalogText(exactCatalog.product_name, "product label");
  const edition = boundedCatalogText(exactCatalog.edition, "edition label");
  const dictionaryVersion = boundedCatalogText(
    exactCatalog.source_release_version,
    "dictionary version label",
  );
  assertNoSensitiveDetail(JSON.stringify({
    catalog_version_id: exactVersionId,
    provider_name: provider,
    product_name: product,
    edition,
    source_release_version: dictionaryVersion,
  }), "Exact catalog selection evidence");

  const inventory = page.locator('aside[aria-label="Installed bureau catalog versions"]');
  await inventory.waitFor();
  const exactAccessibleName = new RegExp(
    `^${escapeRegExp(provider)}\\s*\\/\\s*${escapeRegExp(product)}[\\s\\S]*${escapeRegExp(edition)}\\s*\\/\\s*${escapeRegExp(dictionaryVersion)}`,
  );
  const exactButton = inventory.getByRole("button", { name: exactAccessibleName });
  const buttonCount = await exactButton.count();
  if (buttonCount !== 1) {
    throw new Error("The exact expected catalog did not map to one visible inventory control.");
  }
  await exactButton.click();
  await page.getByText(exactVersionId, { exact: true }).waitFor();
  if ((await exactButton.getAttribute("aria-pressed")) !== "true") {
    throw new Error("The exact catalog inventory control did not enter the selected state.");
  }
  if ((await page.getByTestId("bureau-catalog-selection-required").count()) !== 0) {
    throw new Error("Restricted catalog details remained blocked after exact selection.");
  }
}

async function assertTwoEntitledProviders(page) {
  const primary = page.getByRole("button", {
    name: /Synthetic Bureau 1 \/ Synthetic Operational Attributes/,
  });
  const secondary = page.getByRole("button", {
    name: /Synthetic Bureau 2 \/ Synthetic Operational Attributes/,
  });
  await primary.waitFor();
  await secondary.waitFor();
}

async function probeProjectAccess(page, ownProject, otherProject) {
  const result = await page.evaluate(async ({ api, own, other }) => {
    const request = async (projectId) => {
      const response = await fetch(
        `${api}/isolated/project-identities/${encodeURIComponent(projectId)}`,
        { credentials: "include", headers: { Accept: "application/json" } },
      );
      return { status: response.status, body: await response.text() };
    };
    const [ownResponse, crossResponse] = await Promise.all([
      request(own.projectId),
      request(other.projectId),
    ]);
    return { ownResponse, crossResponse };
  }, { api: `${backendUrl}/api`, own: ownProject, other: otherProject });

  if (result.ownResponse.status !== 200) {
    throw new Error("An entitled synthetic user could not retrieve its own project identity.");
  }
  let ownPayload;
  try {
    ownPayload = JSON.parse(result.ownResponse.body);
  } catch {
    throw new Error("The own-project response was not bounded JSON.");
  }
  const identity = ownPayload?.identity;
  const expectedKeys = [
    "binding_revision",
    "classification",
    "dataset_id",
    "dataset_version_id",
    "project_id",
  ];
  if (
    ownPayload?.ok !== true
    || !identity
    || Object.keys(identity).sort().join("|") !== expectedKeys.join("|")
    || identity.project_id !== ownProject.projectId
    || identity.dataset_id !== ownProject.datasetId
    || identity.dataset_version_id !== ownProject.datasetVersionId
    || identity.binding_revision !== 1
    || identity.classification !== "synthetic_isolated_project_identity"
  ) {
    throw new Error("The own-project response returned contradictory synthetic identity.");
  }
  const renderedOwn = JSON.stringify(ownPayload);
  if (
    renderedOwn.includes(otherProject.projectId)
    || renderedOwn.includes(otherProject.datasetId)
    || renderedOwn.includes(otherProject.datasetVersionId)
    || renderedOwn.includes(otherProject.principal)
    || renderedOwn.includes(ownProject.principal)
  ) {
    throw new Error("The own-project response leaked a user binding or another project identity.");
  }
  if (result.crossResponse.status !== 403) {
    throw new Error("A cross-project synthetic identity request was not denied.");
  }
  const renderedCross = result.crossResponse.body;
  for (const forbidden of [
    ownProject.projectId,
    ownProject.datasetId,
    ownProject.datasetVersionId,
    otherProject.projectId,
    otherProject.datasetId,
    otherProject.datasetVersionId,
    ownProject.principal,
    otherProject.principal,
  ]) {
    if (renderedCross.includes(forbidden)) {
      throw new Error("A cross-project denial leaked synthetic project content.");
    }
  }
  assertNoSensitiveDetail(renderedOwn, "Own-project identity response");
  assertNoSensitiveDetail(renderedCross, "Cross-project denial response");
  const browserStorage = await page.evaluate(() => ({
    local: Object.fromEntries(
      Array.from({ length: localStorage.length }, (_, index) => {
        const key = localStorage.key(index);
        return [key, key === null ? null : localStorage.getItem(key)];
      }).filter(([key]) => key !== null),
    ),
    session: Object.fromEntries(
      Array.from({ length: sessionStorage.length }, (_, index) => {
        const key = sessionStorage.key(index);
        return [key, key === null ? null : sessionStorage.getItem(key)];
      }).filter(([key]) => key !== null),
    ),
  }));
  const renderedStorage = JSON.stringify(browserStorage);
  for (const forbidden of [
    otherProject.projectId,
    otherProject.datasetId,
    otherProject.datasetVersionId,
    otherProject.principal,
  ]) {
    if (renderedStorage.includes(forbidden)) {
      throw new Error("Browser storage contained another user's project identity.");
    }
  }
  assertNoSensitiveDetail(renderedStorage, "Project-scoped browser storage");
  return { ownStatus: 200, crossStatus: 403 };
}

async function runProjectIsolationProbe(ownProject, otherProject) {
  const evidence = {};
  const reloadAttempts = projectReloadAttemptsPerProject;
  let reloadSuccesses = 0;
  let ownRetrievals = 0;
  let crossProjectDenials = 0;
  const context = await openPersistentContext(ownProject.profile, {
    ...commonHeaders,
    "X-Synthetic-Principal": ownProject.principal,
    "X-Synthetic-Role": "user",
  });
  try {
    const page = context.pages()[0] ?? (await context.newPage());
    page.setDefaultTimeout(120_000);
    observeNetwork(page, evidence);
    await page.goto(routeUrl, { waitUntil: "domcontentloaded" });
    await page.getByRole("heading", { name: "Administrative access required" }).waitFor();
    const initialAuth = evidence.authResponses.find((item) => item.cycle === 1);
    if (!initialAuth || initialAuth.status !== 200) {
      throw new Error("The project-scoped probe did not establish authenticated readiness.");
    }
    let probe = await probeProjectAccess(page, ownProject, otherProject);
    ownRetrievals += probe.ownStatus === 200 ? 1 : 0;
    crossProjectDenials += probe.crossStatus === 403 ? 1 : 0;

    for (let reload = 1; reload <= reloadAttempts; reload += 1) {
      const cycle = evidence.nextCycle();
      await page.reload({ waitUntil: "domcontentloaded" });
      await page.getByRole("heading", { name: "Administrative access required" }).waitFor();
      const auth = evidence.authResponses.find((item) => item.cycle === cycle);
      if (!auth || auth.status !== 200) {
        throw new Error("A project-scoped authenticated reload did not restore the user.");
      }
      probe = await probeProjectAccess(page, ownProject, otherProject);
      ownRetrievals += probe.ownStatus === 200 ? 1 : 0;
      crossProjectDenials += probe.crossStatus === 403 ? 1 : 0;
      reloadSuccesses += 1;
    }
    await page.evaluate(({ projectId, reloads }) => {
      const panel = document.createElement("section");
      panel.setAttribute("data-testid", "synthetic-project-isolation-evidence");
      panel.style.cssText = "position:fixed;left:24px;bottom:24px;z-index:2147483647;background:#fff;border:2px solid #0f766e;border-radius:8px;padding:16px;color:#0f172a;box-shadow:0 8px 30px rgba(15,23,42,.2);font:14px/1.4 sans-serif";
      panel.textContent = `Isolated acceptance: ${projectId} own identity 200; cross-project 403; authenticated reloads ${reloads}/${reloads}.`;
      document.body.append(panel);
    }, { projectId: ownProject.projectId, reloads: reloadSuccesses });
    assertNoSensitiveDetail(await page.locator("body").innerText(), "Project isolation UI evidence");
    await page.screenshot({
      path: path.join(outputDirectory, ownProject.screenshot),
      fullPage: true,
    });
  } finally {
    await context.close();
  }
  if (
    reloadSuccesses !== reloadAttempts
    || ownRetrievals !== reloadAttempts + 1
    || crossProjectDenials !== reloadAttempts + 1
  ) {
    throw new Error("The bounded project isolation probe was incomplete.");
  }
  return {
    project_id: ownProject.projectId,
    principal: ownProject.principal,
    reload_attempts: reloadAttempts,
    reload_successes: reloadSuccesses,
    own_identity_retrievals: ownRetrievals,
    cross_project_denials: crossProjectDenials,
  };
}

const adminEvidence = {};
let authenticatedReloadSuccesses = 0;
const adminContext = await openPersistentContext("admin-entitled", {
  ...commonHeaders,
  "X-Synthetic-Principal": "synthetic-admin",
  "X-Synthetic-Role": "admin",
  "X-Synthetic-Auth-Delay-Ms": "900",
});
try {
  const page = adminContext.pages()[0] ?? (await adminContext.newPage());
  page.setDefaultTimeout(120_000);
  observeNetwork(page, adminEvidence);
  await page.goto(routeUrl, { waitUntil: "domcontentloaded" });
  await page.getByText("Loading ATLAS security context...", { exact: true }).waitFor();
  await page.getByRole("heading", { name: "Bureau Catalog Administration" }).waitFor();
  await page.getByTitle("Signed in as Synthetic acceptance principal").waitFor();
  await assertTwoEntitledProviders(page);
  await selectExactExpectedCatalog(page, expectedSecondaryVersionId);
  await selectExactExpectedCatalog(page, expectedVersionId);
  const firstAuth = adminEvidence.authResponses.find((item) => item.cycle === 1);
  const firstCatalog = adminEvidence.catalogRequests.find((item) => item.cycle === 1);
  if (!firstAuth || firstAuth.status !== 200 || !firstCatalog || firstCatalog.sequence <= firstAuth.sequence) {
    throw new Error("Catalog administration did not wait for authenticated readiness.");
  }
  assertNoSensitiveDetail(await page.locator("body").innerText(), "Entitled administrator UI");
  await page.screenshot({
    path: path.join(outputDirectory, "production-auth-admin-initial.png"),
    fullPage: true,
  });

  for (let reload = 1; reload <= authenticatedReloadAttempts; reload += 1) {
    const cycle = adminEvidence.nextCycle();
    await page.reload({ waitUntil: "domcontentloaded" });
    await page.getByText("Loading ATLAS security context...", { exact: true }).waitFor();
    await page.getByRole("heading", { name: "Bureau Catalog Administration" }).waitFor();
    await page.getByTitle("Signed in as Synthetic acceptance principal").waitFor();
    await assertTwoEntitledProviders(page);
    await selectExactExpectedCatalog(page, expectedVersionId);
    const auth = adminEvidence.authResponses.find((item) => item.cycle === cycle);
    const catalog = adminEvidence.catalogRequests.find((item) => item.cycle === cycle);
    if (!auth || auth.status !== 200 || !catalog || catalog.sequence <= auth.sequence) {
      throw new Error("Authenticated reload did not restore identity and entitlement in order.");
    }
    authenticatedReloadSuccesses += 1;
  }
  assertNoSensitiveDetail(await page.locator("body").innerText(), "Reloaded administrator UI");
  await page.screenshot({
    path: path.join(outputDirectory, "production-auth-admin-reload.png"),
    fullPage: true,
  });
} finally {
  await adminContext.close();
}

const unauthEvidence = {};
const unauthContext = await openPersistentContext("unauthenticated");
try {
  const page = unauthContext.pages()[0] ?? (await unauthContext.newPage());
  page.setDefaultTimeout(120_000);
  observeNetwork(page, unauthEvidence);
  await page.goto(routeUrl, { waitUntil: "domcontentloaded" });
  await page.getByRole("heading", { name: "Sign in to ATLAS" }).waitFor();
  if (!new URL(page.url()).pathname.endsWith("/login")) {
    throw new Error("Unauthenticated navigation did not fail closed to sign-in.");
  }
  if (!new URL(page.url()).searchParams.get("returnTo")?.includes("/admin/bureau-catalogs")) {
    throw new Error("Unauthenticated navigation did not preserve the bounded same-origin return path.");
  }
  const emailInput = page.getByLabel("Email", { exact: true });
  await emailInput.fill("");
  if ((await emailInput.inputValue()) !== "") {
    throw new Error("The unauthenticated screenshot email field could not be sanitized.");
  }
  const auth = unauthEvidence.authResponses.find((item) => item.status === 401);
  if (!auth) throw new Error("Unauthenticated denial did not return HTTP 401.");
  if (unauthEvidence.catalogRequests.length !== 0) {
    throw new Error("Unauthenticated navigation issued a catalog request.");
  }
  const body = await page.locator("body").innerText();
  if (body.includes(expectedVersionId)) throw new Error("Unauthenticated UI exposed a catalog version.");
  assertNoSensitiveDetail(body, "Unauthenticated UI");
  await page.screenshot({
    path: path.join(outputDirectory, "production-auth-unauthenticated-denial.png"),
    fullPage: true,
  });
} finally {
  await unauthContext.close();
}

const roleEvidence = {};
const roleContext = await openPersistentContext("non-admin-entitled", {
  ...commonHeaders,
  "X-Synthetic-Principal": "synthetic-reader",
  "X-Synthetic-Role": "user",
});
try {
  const page = roleContext.pages()[0] ?? (await roleContext.newPage());
  page.setDefaultTimeout(120_000);
  observeNetwork(page, roleEvidence);
  await page.goto(routeUrl, { waitUntil: "domcontentloaded" });
  await page.getByRole("heading", { name: "Administrative access required" }).waitFor();
  if (roleEvidence.catalogRequests.length !== 0) {
    throw new Error("The client role gate issued a restricted catalog request.");
  }
  const body = await page.locator("body").innerText();
  if (body.includes(expectedVersionId)) throw new Error("Non-admin UI exposed a catalog version.");
  assertNoSensitiveDetail(body, "Non-admin UI");
  await page.screenshot({
    path: path.join(outputDirectory, "production-auth-role-denial.png"),
    fullPage: true,
  });
} finally {
  await roleContext.close();
}

const entitlementEvidence = {};
const entitlementContext = await openPersistentContext("admin-unentitled", {
  ...commonHeaders,
  "X-Synthetic-Principal": "synthetic-admin-unentitled",
  "X-Synthetic-Role": "admin",
});
try {
  const page = entitlementContext.pages()[0] ?? (await entitlementContext.newPage());
  page.setDefaultTimeout(120_000);
  observeNetwork(page, entitlementEvidence);
  await page.goto(routeUrl, { waitUntil: "domcontentloaded" });
  await page.getByRole("heading", { name: "Bureau Catalog Administration" }).waitFor();
  await page.getByRole("heading", { name: "No entitled catalog versions" }).waitFor();
  const denial = await page.evaluate(async ({ api, versionId }) => {
    const response = await fetch(`${api}/admin/bureau-catalogs/${encodeURIComponent(versionId)}/validate`, {
      method: "POST",
      credentials: "include",
      headers: { Accept: "application/json", "Content-Type": "application/json" },
      body: "{}",
    });
    return { status: response.status, body: await response.text() };
  }, { api: `${backendUrl}/api`, versionId: expectedVersionId });
  if (denial.status !== 403) throw new Error("Unentitled administrator exact-version request was not denied.");
  if (denial.body.includes(expectedVersionId)) throw new Error("Entitlement denial echoed catalog identity.");
  assertNoSensitiveDetail(denial.body, "Entitlement denial response");
  const body = await page.locator("body").innerText();
  if (body.includes(expectedVersionId)) throw new Error("Unentitled administrator UI exposed a catalog version.");
  assertNoSensitiveDetail(body, "Unentitled administrator UI");
  await page.screenshot({
    path: path.join(outputDirectory, "production-auth-entitlement-denial.png"),
    fullPage: true,
  });
} finally {
  await entitlementContext.close();
}

const projectAlphaEvidence = await runProjectIsolationProbe(projectAlpha, projectBeta);
const projectBetaEvidence = await runProjectIsolationProbe(projectBeta, projectAlpha);
const projectReloadAttempts = (
  projectAlphaEvidence.reload_attempts + projectBetaEvidence.reload_attempts
);
const projectReloadSuccesses = (
  projectAlphaEvidence.reload_successes + projectBetaEvidence.reload_successes
);

if (networkEvidence.unexpected_fetch_xhr_urls.length !== 0) {
  throw new Error("The production frontend contacted a non-isolated API origin.");
}
if (networkEvidence.websocket_count !== 0) {
  throw new Error("The production frontend opened a WebSocket/HMR connection.");
}
if (networkEvidence.blocked_request_count !== 0 || networkEvidence.live_port_contact_count !== 0) {
  throw new Error("The production browser attempted a prohibited origin or live port.");
}

process.stdout.write(JSON.stringify({
  ok: true,
  synthetic_run_id: syntheticRunId || null,
  headed_browser: headed,
  production_route: true,
  initial_load_waited_for_auth_readiness: true,
  authenticated_reload_restored_user: true,
  authenticated_reload_restored_entitlement: true,
  authenticated_reload_attempts: authenticatedReloadAttempts + projectReloadAttempts,
  authenticated_reload_successes: authenticatedReloadSuccesses + projectReloadSuccesses,
  authenticated_user_count: 5,
  authenticated_provider_count: 2,
  exact_expected_catalog_selected: true,
  exact_selection_after_every_reload: true,
  first_or_latest_catalog_fallback_used: false,
  authenticated_project_count: 2,
  cross_user_contamination: 0,
  cross_project_contamination: 0,
  cross_provider_contamination: 0,
  project_authorization_probe: {
    status: "verified",
    synthetic_project_count: 2,
    bindings: [projectAlphaEvidence, projectBetaEvidence],
    cross_project_content_leaks: 0,
  },
  soak_schema_note: "Two synthetic project-user bindings were verified across authenticated reloads.",
  unauthenticated_http_status: 401,
  unauthenticated_denial_no_catalog_request: true,
  non_admin_role_gate_no_catalog_request: true,
  unentitled_admin_exact_request_status: 403,
  admin_route_requires_role_and_entitlement: true,
  no_restricted_details_exposed: true,
  network_contact_guard: {
    fetch_xhr_count: networkEvidence.fetch_xhr_count,
    isolated_backend_fetch_xhr_count: networkEvidence.isolated_backend_fetch_xhr_count,
    unexpected_fetch_xhr_count: networkEvidence.unexpected_fetch_xhr_urls.length,
    websocket_count: networkEvidence.websocket_count,
    blocked_request_count: networkEvidence.blocked_request_count,
    live_port_contact_count: networkEvidence.live_port_contact_count,
  },
  screenshot_files: [
    "production-auth-admin-initial.png",
    "production-auth-admin-reload.png",
    "production-auth-unauthenticated-denial.png",
    "production-auth-role-denial.png",
    "production-auth-entitlement-denial.png",
    projectAlpha.screenshot,
    projectBeta.screenshot,
  ],
}));
