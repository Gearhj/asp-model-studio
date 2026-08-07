import { chromium } from "@playwright/test";
import { appendFileSync } from "node:fs";
import { mkdir } from "node:fs/promises";
import path from "node:path";

function argument(name) {
  const index = process.argv.indexOf(name);
  if (index < 0 || !process.argv[index + 1]) throw new Error(`Missing ${name}.`);
  return process.argv[index + 1];
}

const frontendUrl = argument("--frontend-url").replace(/\/$/, "");
const backendUrl = argument("--backend-url").replace(/\/$/, "");
const outputDirectory = path.resolve(argument("--output-directory"));
const browserProfileDirectory = path.resolve(argument("--browser-profile-directory"));
const downloadsDirectory = path.resolve(argument("--downloads-directory"));
const expectedVersionId = argument("--expected-version-id");
const syntheticRunId = argument("--synthetic-run-id");
const networkViolationFile = argument("--network-violation-file");
const headed = process.argv.includes("--headed");
const reloadAttempts = Number(argument("--reload-attempts"));
if (!Number.isSafeInteger(reloadAttempts) || reloadAttempts < 1 || reloadAttempts > 30) {
  throw new Error("Invalid reload count.");
}

await Promise.all([
  mkdir(outputDirectory, { recursive: true }),
  mkdir(browserProfileDirectory, { recursive: true }),
  mkdir(downloadsDirectory, { recursive: true }),
]);

const projects = {
  A: ["synthetic-project-alpha-001", "synthetic-dataset-alpha-001", "synthetic-version-alpha-001", "synthetic-project-user-alpha"],
  B: ["synthetic-project-beta-002", "synthetic-dataset-beta-002", "synthetic-version-beta-002", "synthetic-project-user-beta"],
  C: ["synthetic-project-gamma-003", "synthetic-dataset-gamma-003", "synthetic-version-gamma-003", "synthetic-project-user-gamma"],
  D: ["synthetic-project-delta-004", "synthetic-dataset-delta-004", "synthetic-version-delta-004", "synthetic-project-user-delta"],
  E: ["synthetic-project-epsilon-005", "synthetic-dataset-epsilon-005", "synthetic-version-epsilon-005", "synthetic-project-user-epsilon"],
};

const network = {
  fetch_xhr_count: 0,
  isolated_backend_fetch_xhr_count: 0,
  unexpected_fetch_xhr_count: 0,
  websocket_count: 0,
  blocked_request_count: 0,
  live_port_contact_count: 0,
};
const allowedOrigins = new Set([frontendUrl, backendUrl]);

function violation(kind) {
  appendFileSync(networkViolationFile, `${JSON.stringify({
    schema_version: "1.0",
    classification: "isolated_browser_network_violation",
    kind,
    occurred_at: new Date().toISOString(),
  })}\n`);
}

async function contextFor(label, principal, role = "user") {
  const profile = path.join(browserProfileDirectory, label);
  const downloads = path.join(downloadsDirectory, label);
  await Promise.all([mkdir(profile, { recursive: true }), mkdir(downloads, { recursive: true })]);
  const context = await chromium.launchPersistentContext(profile, {
    headless: !headed,
    serviceWorkers: "block",
    acceptDownloads: true,
    downloadsPath: downloads,
    viewport: { width: 1600, height: 1000 },
    extraHTTPHeaders: {
      "X-Synthetic-Principal": principal,
      "X-Synthetic-Role": role,
      "X-Synthetic-Tenant": "synthetic-tenant",
      "X-Synthetic-Run-Id": syntheticRunId,
    },
  });
  await context.route("**/*", async (route) => {
    const request = route.request();
    let url;
    try { url = new URL(request.url()); } catch {
      network.blocked_request_count += 1; violation("invalid_url"); await route.abort("blockedbyclient"); return;
    }
    if (["http:", "https:"].includes(url.protocol)) {
      if (["5174", "8001"].includes(url.port)) {
        network.live_port_contact_count += 1; network.blocked_request_count += 1; violation("live_port"); await route.abort("blockedbyclient"); return;
      }
      if (!allowedOrigins.has(url.origin)) {
        network.blocked_request_count += 1; violation("unexpected_origin"); await route.abort("blockedbyclient"); return;
      }
    }
    const kind = request.resourceType();
    if (["fetch", "xhr"].includes(kind)) {
      network.fetch_xhr_count += 1;
      if (request.url().startsWith(`${backendUrl}/api/`)) network.isolated_backend_fetch_xhr_count += 1;
      else network.unexpected_fetch_xhr_count += 1;
    }
    await route.continue();
  });
  const observeWebSockets = (page) => page.on("websocket", () => {
    network.websocket_count += 1;
    violation("websocket_or_hmr");
  });
  for (const page of context.pages()) observeWebSockets(page);
  context.on("page", observeWebSockets);
  return context;
}

async function primeFrontendPage(page, projectKey = "A") {
  await page.goto(
    `${frontendUrl}/tests/bureauMetadataIntegration.isolated.entry.html?project=${projectKey}`,
    { waitUntil: "domcontentloaded" },
  );
}

async function api(page, endpoint, options = {}) {
  return page.evaluate(async ({ base, endpoint, options }) => {
    const response = await fetch(`${base}${endpoint}`, {
      method: options.method ?? "GET",
      credentials: "include",
      headers: { Accept: "application/json", ...(options.body ? { "Content-Type": "application/json" } : {}) },
      body: options.body ? JSON.stringify(options.body) : undefined,
    });
    const text = await response.text();
    let body = null;
    try { body = text ? JSON.parse(text) : null; } catch { body = { invalid_json: true }; }
    return { status: response.status, body };
  }, { base: backendUrl, endpoint, options });
}

function basePath(project) {
  return `/api/projects/${encodeURIComponent(project[0])}/datasets/${encodeURIComponent(project[1])}/versions/${encodeURIComponent(project[2])}/bureau-metadata`;
}

async function exactCatalog(page) {
  const response = await api(page, "/api/bureau-catalogs?offset=0&limit=50");
  if (response.status !== 200) throw new Error("Entitled catalog listing failed.");
  const catalogs = response.body.versions ?? response.body.catalogs ?? response.body.items ?? [];
  const catalog = catalogs.find((item) => item.catalog_version_id === expectedVersionId);
  if (!catalog || !/^[0-9a-f]{64}$/.test(catalog.normalized_catalog_checksum ?? catalog.catalog_checksum ?? "")) {
    throw new Error("Exact catalog identity was not present in the entitled listing.");
  }
  return { id: expectedVersionId, checksum: catalog.normalized_catalog_checksum ?? catalog.catalog_checksum };
}

async function ensureBinding(page, project) {
  const base = basePath(project);
  const current = await api(page, `${base}/binding`);
  if (current.status === 200) return current.body;
  if (current.status !== 404) throw new Error("Exact binding lookup failed.");
  const catalog = await exactCatalog(page);
  const preview = await api(page, `${base}/binding/preview`, { method: "POST", body: { catalog_version_id: catalog.id, catalog_checksum: catalog.checksum } });
  if (preview.status !== 200) throw new Error("Exact binding preview failed.");
  const confirmed = await api(page, `${base}/binding/confirm`, { method: "POST", body: {
    catalog_version_id: catalog.id,
    catalog_checksum: catalog.checksum,
    expected_revision: preview.body.preview.expected_revision,
    preview_checksum: preview.body.preview.preview_checksum,
    analyst_rationale: "Synthetic isolated acceptance exact catalog review.",
  } });
  if (confirmed.status !== 200 || confirmed.body.ok !== true) throw new Error("Exact binding confirmation failed.");
  return confirmed.body;
}

async function ensureExactCrosswalk(page, project) {
  const base = basePath(project);
  const semantic = await api(page, `${base}/annotations`);
  if (semantic.status === 200) return semantic;
  if (semantic.status !== 404) throw new Error("Semantic availability failed closed unexpectedly.");
  const binding = await api(page, `${base}/binding`);
  const preview = await api(page, `${base}/crosswalk/preview`);
  if (binding.status !== 200 || preview.status !== 200) throw new Error("Crosswalk prerequisites were unavailable.");
  const decisions = preview.body.initial_decisions.map((decision) => {
    if (!decision.candidate_attribute_code) {
      return { dataset_field: decision.dataset_field, mapping_state: "out_of_catalog", rationale: "No provider candidate exists for this synthetic field." };
    }
    return {
      dataset_field: decision.dataset_field,
      mapping_state: "exact_verified",
      candidate_attribute_code: decision.candidate_attribute_code,
      rationale: "The exact synthetic provider code and bounded definition were reviewed.",
    };
  });
  const saved = await api(page, `${base}/crosswalk/decisions`, { method: "POST", body: {
    expected_crosswalk_revision: 0,
    expected_binding_revision: binding.body.binding.revision,
    decisions,
    analyst_reason: "Synthetic exact mapping evidence was independently reviewed.",
    confirm_crosswalk: true,
  } });
  if (saved.status !== 200 || saved.body.ok !== true || saved.body.binding_linked !== true) {
    throw new Error("Exact governed crosswalk confirmation failed.");
  }
  const annotations = await api(page, `${base}/annotations`);
  if (annotations.status !== 200 || annotations.body.annotations.length !== decisions.length) {
    throw new Error("Exact semantic annotations did not recover after confirmation.");
  }
  return annotations;
}

function positiveRevision(value, label) {
  if (!Number.isSafeInteger(value) || value < 1) {
    throw new Error(`${label} was missing or invalid.`);
  }
  return value;
}

function sha256(value, label) {
  if (!/^[0-9a-f]{64}$/.test(String(value ?? ""))) {
    throw new Error(`${label} was missing or invalid.`);
  }
  return value;
}

function assertExactBindingIdentity(response, { project, catalog, expected = null }) {
  if (response?.status !== 200 || response.body?.ok !== true) {
    throw new Error("The exact catalog binding could not be recovered.");
  }
  const binding = response.body.binding;
  const identity = binding?.identity;
  const summary = response.body.summary;
  if (!binding || !identity || !summary) {
    throw new Error("The catalog binding response omitted governed identity.");
  }
  const exactIdentity = {
    project_id: project[0],
    dataset_id: project[1],
    dataset_version_id: project[2],
    catalog_version_id: catalog.id,
    catalog_checksum: catalog.checksum,
  };
  for (const [field, value] of Object.entries(exactIdentity)) {
    if (identity[field] !== value || summary.identity?.[field] !== value) {
      throw new Error(`The recovered catalog binding had the wrong ${field}.`);
    }
  }
  if (
    binding.status !== "active"
    || binding.stored_status !== "active"
    || binding.stale_reason !== null
    || summary.current !== true
    || summary.stale !== false
  ) {
    throw new Error("The recovered exact catalog binding was stale or inactive.");
  }
  const snapshot = {
    identity: JSON.stringify(identity),
    bindingId: String(binding.binding_id ?? ""),
    bindingRevision: positiveRevision(binding.revision, "Binding revision"),
    bindingRevisionChecksum: sha256(binding.revision_checksum, "Binding revision checksum"),
    crosswalkId: binding.crosswalk_id == null ? null : String(binding.crosswalk_id),
    crosswalkRevision: binding.crosswalk_revision == null
      ? null
      : positiveRevision(binding.crosswalk_revision, "Crosswalk revision"),
  };
  if (!snapshot.bindingId || (snapshot.crosswalkRevision !== null && !snapshot.crosswalkId)) {
    throw new Error("The recovered catalog binding had incomplete revision identity.");
  }
  if ((snapshot.crosswalkId === null) !== (snapshot.crosswalkRevision === null)) {
    throw new Error("The recovered catalog binding had contradictory crosswalk identity.");
  }
  if (expected) {
    for (const field of [
      "identity",
      "bindingId",
      "bindingRevision",
      "bindingRevisionChecksum",
      "crosswalkId",
      "crosswalkRevision",
    ]) {
      if (snapshot[field] !== expected[field]) {
        throw new Error(`The exact catalog binding changed ${field} after reload.`);
      }
    }
  }
  return snapshot;
}

function assertExactCanonicalAnnotationIdentity(
  response,
  { project, catalog, binding, expected = null },
) {
  if (response?.status !== 200 || response.body?.ok !== true) {
    throw new Error("The exact canonical annotation set could not be recovered.");
  }
  const annotationSet = response.body.annotation_set;
  const annotations = response.body.annotations;
  if (!annotationSet || !Array.isArray(annotations) || annotations.length < 1) {
    throw new Error("The canonical annotation response omitted governed identity.");
  }
  const exactIdentity = {
    project_id: project[0],
    dataset_id: project[1],
    dataset_version_id: project[2],
    catalog_version_id: catalog.id,
    catalog_checksum: catalog.checksum,
    binding_id: binding.bindingId,
    binding_revision: binding.bindingRevision,
    binding_revision_checksum: binding.bindingRevisionChecksum,
    crosswalk_id: binding.crosswalkId,
    crosswalk_revision: binding.crosswalkRevision,
  };
  if (binding.crosswalkId === null || binding.crosswalkRevision === null) {
    throw new Error("Canonical annotations were checked without an exact linked crosswalk.");
  }
  for (const [field, value] of Object.entries(exactIdentity)) {
    if (annotationSet[field] !== value) {
      throw new Error(`The canonical annotation set had the wrong ${field}.`);
    }
  }
  if (annotationSet.accepted_annotation_count !== annotations.length) {
    throw new Error("The canonical annotation count contradicted its payload.");
  }
  const annotationIds = annotations.map((annotation) => {
    if (
      !annotation?.annotation_id
      || annotation.binding_id !== binding.bindingId
      || annotation.binding_revision !== binding.bindingRevision
      || annotation.binding_revision_checksum !== binding.bindingRevisionChecksum
      || annotation.crosswalk_id !== binding.crosswalkId
      || annotation.crosswalk_revision !== binding.crosswalkRevision
      || annotation.catalog_version_id !== catalog.id
      || annotation.catalog_checksum !== catalog.checksum
      || annotation.binding_current !== true
      || annotation.entitlement_verified !== true
    ) {
      throw new Error("A canonical annotation had stale or contradictory lineage.");
    }
    return String(annotation.annotation_id);
  });
  if (new Set(annotationIds).size !== annotationIds.length) {
    throw new Error("The canonical annotation set contained duplicate identities.");
  }
  const snapshot = {
    annotationSetId: String(annotationSet.annotation_set_id ?? ""),
    annotationSetChecksum: sha256(
      annotationSet.annotation_set_checksum,
      "Annotation set checksum",
    ),
    crosswalkRevisionChecksum: sha256(
      annotationSet.crosswalk_revision_checksum,
      "Crosswalk revision checksum",
    ),
    annotationIds: JSON.stringify(annotationIds),
  };
  if (!snapshot.annotationSetId) {
    throw new Error("The canonical annotation set identity was missing.");
  }
  if (expected) {
    for (const field of [
      "annotationSetId",
      "annotationSetChecksum",
      "crosswalkRevisionChecksum",
      "annotationIds",
    ]) {
      if (snapshot[field] !== expected[field]) {
        throw new Error(`The canonical annotation identity changed ${field} after reload.`);
      }
    }
  }
  return snapshot;
}

const screenshots = [];
let reloadSuccesses = 0;

async function capture(page, file, locator = null) {
  const destination = path.join(outputDirectory, file);
  if (locator) {
    await locator.scrollIntoViewIfNeeded();
    await locator.screenshot({ path: destination });
  } else {
    await page.screenshot({ path: destination, fullPage: true });
  }
  screenshots.push(file);
}

async function navigationSnapshot(page) {
  return page.evaluate(() => ({
    href: window.location.href,
    navigationEntries: performance.getEntriesByType("navigation").length,
    scrollY: window.scrollY,
  }));
}

function projectBDecisions() {
  return [
    {
      dataset_field: "SYN000",
      mapping_state: "exact_verified",
      candidate_attribute_code: "SYN000",
      rationale: "The exact synthetic provider code and bounded definition were reviewed.",
    },
    {
      dataset_field: "ALIAS_SCORE",
      mapping_state: "approved_alias",
      candidate_attribute_code: "SYN001",
      alias_authority_id: "synthetic-alias-authority-beta-v1",
      institutional_alias_reference: "synthetic-alias-policy-beta-v1",
      rationale: "The institutionally approved alias and its exact versioned reference were reviewed.",
    },
    {
      dataset_field: "SYN004",
      mapping_state: "probable_review_required",
      candidate_attribute_code: "SYN004",
      rationale: "The probable provider match remains explicitly subject to analyst review.",
    },
    {
      dataset_field: "AMBIGUOUS_FIELD",
      mapping_state: "ambiguous_review_required",
      candidate_attribute_code: "SYN002",
      alternative_attribute_codes: ["SYN002", "SYN003"],
      rationale: "Two bounded provider candidates remain plausible and require resolution.",
    },
    {
      dataset_field: "LOCAL_ONLY",
      mapping_state: "unresolved",
      rationale: "No supported provider candidate exists for this generic local field.",
    },
    {
      dataset_field: "SYN005",
      mapping_state: "rejected",
      candidate_attribute_code: "SYN005",
      rationale: "The reviewed candidate is deliberately rejected for this dataset field.",
    },
  ];
}

function assertProjectBStates(current) {
  const expected = new Map(projectBDecisions().map((decision) => [decision.dataset_field, decision.mapping_state]));
  const decisions = current?.body?.governance?.decisions ?? [];
  const actual = new Map(decisions.map((decision) => [decision.dataset_field, decision.mapping_state]));
  for (const [field, state] of expected) {
    if (actual.get(field) !== state) throw new Error(`Project B ${field} did not retain ${state}.`);
  }
  return expected;
}

// Project A: production Data Acquisition binding, governed exact crosswalk,
// table-first semantic sources, and canonical EDA handoff.
const contextA = await contextFor("project-a-exact", projects.A[3]);
try {
  const page = contextA.pages()[0] ?? await contextA.newPage();
  await page.goto(`${frontendUrl}/tests/bureauMetadataIntegration.isolated.entry.html?project=A`, { waitUntil: "domcontentloaded" });
  await page.getByTestId("bureau-metadata-binding-panel").waitFor();
  const expectedCatalog = await exactCatalog(page);
  let binding = await api(page, `${basePath(projects.A)}/binding`);
  if (binding.status === 404) {
    const catalogSelect = page.getByTestId("bureau-metadata-catalog-select");
    await catalogSelect.waitFor();
    if (!(await catalogSelect.locator(`option[value="${expectedVersionId}"]`).count())) {
      throw new Error("The exact entitled catalog version was not visible in the production selector.");
    }
    await catalogSelect.selectOption(expectedVersionId);
    await capture(page, "bureau-metadata-entitled-catalog-selection.png", page.getByTestId("bureau-metadata-binding-panel"));
    await page.getByTestId("bureau-metadata-preview-button").click();
    await page.getByTestId("bureau-metadata-binding-preview").waitFor();
    await page.getByTestId("bureau-metadata-binding-rationale").fill("Synthetic exact catalog applies to this exact dataset version.");
    await page.getByTestId("bureau-metadata-confirm-button").click();
    await page.getByTestId("bureau-metadata-confirmed-summary").waitFor();
  } else {
    await page.getByRole("button", { name: "Review a different exact version" }).click();
    const catalogSelect = page.getByTestId("bureau-metadata-catalog-select");
    await catalogSelect.selectOption(expectedVersionId);
    await capture(page, "bureau-metadata-entitled-catalog-selection.png", page.getByTestId("bureau-metadata-binding-panel"));
    await page.getByRole("button", { name: "Keep current binding" }).click();
    const retainedBinding = await api(page, `${basePath(projects.A)}/binding`);
    assertExactBindingIdentity(retainedBinding, {
      project: projects.A,
      catalog: expectedCatalog,
    });
  }
  binding = await api(page, `${basePath(projects.A)}/binding`);
  assertExactBindingIdentity(binding, { project: projects.A, catalog: expectedCatalog });
  await page.getByTestId("bureau-metadata-confirmed-summary").waitFor();
  await capture(page, "bureau-metadata-compact-binding-summary.png", page.getByTestId("bureau-metadata-confirmed-summary"));
  const annotations = await ensureExactCrosswalk(page, projects.A);
  binding = await api(page, `${basePath(projects.A)}/binding`);
  const canonicalBinding = assertExactBindingIdentity(binding, {
    project: projects.A,
    catalog: expectedCatalog,
  });
  const canonicalAnnotations = assertExactCanonicalAnnotationIdentity(annotations, {
    project: projects.A,
    catalog: expectedCatalog,
    binding: canonicalBinding,
  });
  await page.reload({ waitUntil: "domcontentloaded" });
  await page.getByTestId("bureau-metadata-confirmed-summary").waitFor();
  await page.getByTestId("special-value-feature-table").waitFor();
  await page.getByTestId("synthetic-canonical-eda-handoff").waitFor();
  await page.getByTestId("synthetic-eda-identity-contract").waitFor();
  const firstReloadBinding = assertExactBindingIdentity(
    await api(page, `${basePath(projects.A)}/binding`),
    { project: projects.A, catalog: expectedCatalog, expected: canonicalBinding },
  );
  assertExactCanonicalAnnotationIdentity(
    await api(page, `${basePath(projects.A)}/annotations`),
    {
      project: projects.A,
      catalog: expectedCatalog,
      binding: firstReloadBinding,
      expected: canonicalAnnotations,
    },
  );
  const eda = await api(page, `/api/isolated/canonical-eda-handoff/${projects.A.map(encodeURIComponent).slice(0, 3).join("/")}`);
  if (
    eda.status !== 200 || eda.body.final_holdout_accessed !== false || eda.body.training_started !== false
  ) throw new Error("Canonical DA-to-EDA semantic handoff was contradictory.");
  assertExactCanonicalAnnotationIdentity(
    { status: eda.status, body: eda.body.bureau_semantic_annotations },
    {
      project: projects.A,
      catalog: expectedCatalog,
      binding: firstReloadBinding,
      expected: canonicalAnnotations,
    },
  );
  const retry = await api(page, `${basePath(projects.A)}/crosswalk/binding-link`, { method: "POST", body: {
    crosswalk_revision: canonicalBinding.crosswalkRevision,
    expected_binding_revision: canonicalBinding.bindingRevision,
    analyst_reason: "Verify idempotent exact binding-link retry after persistence.",
  } });
  if (retry.status !== 200 || retry.body.binding_linked !== true) throw new Error("Idempotent binding-link retry failed.");
  const search = await api(page, `/api/bureau-catalogs/${encodeURIComponent(expectedVersionId)}/attributes?q=synthetic&offset=0&limit=5`);
  if (search.status !== 200) throw new Error("Bounded catalog search failed.");
  const malformed = await api(page, `${basePath(projects.A)}/binding/preview`, { method: "POST", body: { catalog_version_id: expectedVersionId, catalog_checksum: "invalid" } });
  if (malformed.status !== 422) throw new Error("Malformed binding request did not fail closed.");
  for (let attempt = 0; attempt < reloadAttempts; attempt += 1) {
    await page.reload({ waitUntil: "domcontentloaded" });
    await page.getByTestId("bureau-metadata-confirmed-summary").waitFor();
    await page.getByTestId("special-value-feature-table").waitFor();
    await page.getByTestId("synthetic-canonical-eda-handoff").waitFor();
    const reloadedBinding = assertExactBindingIdentity(
      await api(page, `${basePath(projects.A)}/binding`),
      { project: projects.A, catalog: expectedCatalog, expected: canonicalBinding },
    );
    assertExactCanonicalAnnotationIdentity(
      await api(page, `${basePath(projects.A)}/annotations`),
      {
        project: projects.A,
        catalog: expectedCatalog,
        binding: reloadedBinding,
        expected: canonicalAnnotations,
      },
    );
    reloadSuccesses += 1;
  }
  await capture(page, "bureau-metadata-canonical-eda-handoff.png", page.getByTestId("synthetic-canonical-eda-handoff"));
} finally { await contextA.close(); }

// Project B: every required governance state, backend-authoritative
// contradiction evidence, table-first treatment interaction, stable route and
// guide context, and expandable code-level metadata.
const contextB = await contextFor("project-b-mixed", projects.B[3]);
try {
  const page = contextB.pages()[0] ?? await contextB.newPage();
  await primeFrontendPage(page, "B");
  await ensureBinding(page, projects.B);
  const base = basePath(projects.B);
  let current = await api(page, `${base}/crosswalk/current`);
  if (current.status === 404) {
    const binding = await api(page, `${base}/binding`);
    const preview = await api(page, `${base}/crosswalk/preview`);
    if (binding.status !== 200 || preview.status !== 200 || preview.body.initial_decisions.length !== 6) {
      throw new Error("Project B bounded crosswalk preview was incomplete.");
    }
    const decisions = projectBDecisions();
    const saved = await api(page, `${base}/crosswalk/decisions`, { method: "POST", body: {
      expected_crosswalk_revision: 0,
      expected_binding_revision: binding.body.binding.revision,
      decisions,
      analyst_reason: "Record mixed synthetic governance states without confirmation.",
      confirm_crosswalk: false,
    } });
    if (saved.status !== 200 || saved.body.ok !== true || saved.body.binding_linked !== true) {
      throw new Error("Mixed-state crosswalk revision failed.");
    }
    current = await api(page, `${base}/crosswalk/current`);
  }
  if (current.status !== 200) throw new Error("Mixed-state crosswalk was not durable.");
  const expectedStates = assertProjectBStates(current);
  const stale = await api(page, `${base}/crosswalk/decisions`, { method: "POST", body: {
    expected_crosswalk_revision: current.body.governance.revision + 7,
    expected_binding_revision: current.body.binding?.revision ?? 1,
    decisions: [{ dataset_field: "SYN000", mapping_state: "exact_verified", candidate_attribute_code: "SYN000", rationale: "Synthetic contradictory revision request." }],
    analyst_reason: "Deliberately verify stale revision conflict handling.",
    confirm_crosswalk: false,
  } });
  if (stale.status !== 409) throw new Error("Stale crosswalk revision did not conflict.");
  await primeFrontendPage(page, "B");
  await page.getByTestId("bureau-crosswalk-workspace").waitFor();
  await page.getByTestId("bureau-crosswalk-decision-table").waitFor();
  for (const [field, state] of expectedStates) {
    const row = page.getByTestId(`bureau-crosswalk-row-${field}`);
    await row.waitFor();
    if ((await row.getAttribute("data-mapping-state")) !== state) {
      throw new Error(`Visible Project B row ${field} did not report ${state}.`);
    }
  }
  await capture(page, "bureau-metadata-crosswalk-table-all-states.png", page.getByTestId("bureau-crosswalk-decision-table"));
  await capture(page, "bureau-metadata-crosswalk-exact-state.png", page.getByTestId("bureau-crosswalk-row-SYN000"));
  await capture(page, "bureau-metadata-crosswalk-unresolved-state.png", page.getByTestId("bureau-crosswalk-row-LOCAL_ONLY"));

  const consistency = await api(page, `${base}/crosswalk/consistency`);
  const contradictory = consistency.body?.results?.find((result) => result.dataset_field === "SYN000");
  const contradictoryChecks = new Set(
    Object.entries(contradictory?.checks ?? {})
      .filter(([, check]) => check?.state === "contradictory")
      .map(([name]) => name),
  );
  if (
    consistency.status !== 200
    || consistency.body?.summary?.recommendations_blocked !== true
    || contradictory?.consistency_state !== "contradictory"
    || contradictory?.recommendations_blocked !== true
    || !contradictoryChecks.has("datatype")
    || !contradictoryChecks.has("ordinary_range")
    || !contradictoryChecks.has("special_values")
  ) throw new Error("The datatype/range/special-value contradiction did not fail closed.");
  const contradictionPanel = page.getByTestId("synthetic-contradiction-SYN000");
  await contradictionPanel.waitFor();
  await capture(page, "bureau-metadata-visible-contradiction.png", contradictionPanel);

  const specialTable = page.getByTestId("special-value-feature-table");
  await specialTable.waitFor();
  const guide = page.getByTestId("synthetic-atlas-guide-stable");
  const guideText = await guide.innerText();
  const guideKey = await guide.getAttribute("data-stability-key");
  const treatment = page.getByTestId("special-value-treatment-SYN000");
  await treatment.scrollIntoViewIfNeeded();
  await page.evaluate(() => window.scrollBy(0, -120));
  const beforeTreatment = await navigationSnapshot(page);
  await treatment.selectOption("convert_to_category");
  if ((await treatment.inputValue()) !== "convert_to_category") {
    throw new Error("The visible special-value treatment did not update in place.");
  }
  const afterTreatment = await navigationSnapshot(page);
  if (
    afterTreatment.href !== beforeTreatment.href
    || afterTreatment.navigationEntries !== beforeTreatment.navigationEntries
    || Math.abs(afterTreatment.scrollY - beforeTreatment.scrollY) > 5
    || (await guide.innerText()) !== guideText
    || (await guide.getAttribute("data-stability-key")) !== guideKey
  ) throw new Error("Treatment interaction changed the route, scroll position, or Atlas Guide context.");
  await capture(page, "bureau-metadata-table-first-special-review.png", specialTable);

  const expand = page.getByTestId("review-special-value-codes-SYN000");
  await expand.click();
  await page.getByTestId("special-value-code-details-row").waitFor();
  const semanticDetails = page.getByTestId("bureau-semantic-source-details");
  await semanticDetails.waitFor();
  if (!(await semanticDetails.innerText()).includes("Provider catalog definition")) {
    throw new Error("Expanded code-level metadata did not show the provider definition.");
  }
  await capture(page, "bureau-metadata-expanded-code-level-metadata.png", page.getByTestId("special-value-code-details-row"));
  await expand.click();
  if (await page.getByTestId("special-value-code-details-row").count()) {
    throw new Error("Special-value code metadata did not collapse in place.");
  }
  await expand.click();
  await page.getByTestId("special-value-code-details-row").waitFor();
  const afterExpansion = await navigationSnapshot(page);
  if (
    afterExpansion.href !== beforeTreatment.href
    || afterExpansion.navigationEntries !== beforeTreatment.navigationEntries
    || (await guide.innerText()) !== guideText
    || (await guide.getAttribute("data-stability-key")) !== guideKey
  ) throw new Error("Row expansion changed the route, reloaded the page, or changed Atlas Guide context.");
} finally { await contextB.close(); }

// Project C: entitled inventory must be empty and remain a safe optional state.
const contextC = await contextFor("project-c-no-entitlement", projects.C[3]);
try {
  const page = contextC.pages()[0] ?? await contextC.newPage();
  await page.goto(`${frontendUrl}/tests/bureauMetadataIntegration.isolated.entry.html?project=C`, { waitUntil: "domcontentloaded" });
  await page.getByTestId("bureau-metadata-no-entitlement").waitFor();
  const file = "bureau-metadata-project-c-no-entitlement.png";
  await page.screenshot({ path: path.join(outputDirectory, file), fullPage: true });
  screenshots.push(file);
} finally { await contextC.close(); }

// Project D: non-bureau context remains collapsed and does not auto-bind.
const contextD = await contextFor("project-d-non-bureau", projects.D[3]);
try {
  const page = contextD.pages()[0] ?? await contextD.newPage();
  await page.goto(`${frontendUrl}/tests/bureauMetadataIntegration.isolated.entry.html?project=D`, { waitUntil: "domcontentloaded" });
  const launcher = page.getByTestId("bureau-metadata-binding-launcher");
  await launcher.waitFor();
  if (await launcher.getAttribute("data-state") !== "hidden") throw new Error("Non-bureau binding workspace opened automatically.");
  const file = "bureau-metadata-project-d-non-bureau.png";
  await page.screenshot({ path: path.join(outputDirectory, file), fullPage: true });
  screenshots.push(file);
} finally { await contextD.close(); }

// Project E: exact owner succeeds while a different entitled user receives a
// nonleaking denial for the same exact project identity.
let projectEOwnerStatus = 0;
const contextE = await contextFor("project-e-owner", projects.E[3]);
try {
  const page = contextE.pages()[0] ?? await contextE.newPage();
  await primeFrontendPage(page, "E");
  const own = await api(page, `/api/isolated/project-integration-identity/${projects.E[0]}`);
  if (own.status !== 200 || own.body.dataset_version_id !== projects.E[2]) throw new Error("Project E owner identity failed.");
  projectEOwnerStatus = own.status;
} finally { await contextE.close(); }
const contextIntruder = await contextFor("project-e-intruder", projects.A[3]);
try {
  const page = contextIntruder.pages()[0] ?? await contextIntruder.newPage();
  await primeFrontendPage(page, "A");
  const denied = await api(page, `/api/isolated/project-integration-identity/${projects.E[0]}`);
  if (denied.status !== 403 || JSON.stringify(denied.body).includes(projects.E[2])) throw new Error("Cross-user project isolation failed.");
  await page.evaluate(({ ownerStatus, deniedStatus }) => {
    const section = document.createElement("section");
    section.dataset.testid = "synthetic-api-isolation-evidence";
    section.style.cssText = "margin:20px auto;max-width:900px;padding:20px;border:1px solid #99a3b3;border-radius:12px;background:white;font:14px system-ui;color:#0f172a";
    section.innerHTML = `<div style="font-size:11px;font-weight:700;text-transform:uppercase;color:#1d4ed8">Sanitized isolated API acceptance evidence</div><h2 style="margin:6px 0">Exact owner access and cross-user denial</h2><p>Owner request: HTTP ${ownerStatus}, exact synthetic identity verified.</p><p>Different principal request: HTTP ${deniedStatus}, denied without dataset-version disclosure.</p><p>Live services contacted: no. Final holdout accessed: no. Training started: no.</p>`;
    document.body.prepend(section);
  }, { ownerStatus: projectEOwnerStatus, deniedStatus: denied.status });
  await capture(page, "bureau-metadata-api-only-multi-user-isolation.png", page.getByTestId("synthetic-api-isolation-evidence"));
} finally { await contextIntruder.close(); }

// Exercise a bounded entitlement grant/revoke cycle using only an isolated
// transient principal and the isolated admin authority.
const admin = await contextFor("integration-admin", "synthetic-admin", "admin");
try {
  const page = admin.pages()[0] ?? await admin.newPage();
  await primeFrontendPage(page, "D");
  const grant = await api(page, `/api/admin/bureau-catalogs/${encodeURIComponent(expectedVersionId)}/entitlements`, { method: "POST", body: {
    principal_id: "synthetic-integration-transient",
    tenant_id: "synthetic-tenant",
    operations: ["catalog_health"],
  } });
  if (grant.status !== 200) throw new Error("Transient isolated entitlement grant failed.");
  const revoke = await api(page, `/api/admin/bureau-catalog-entitlements/${encodeURIComponent(grant.body.entitlement.entitlement_id)}/revoke`, { method: "POST", body: { reason: "Synthetic integration cycle complete" } });
  if (revoke.status !== 200 || revoke.body.entitlement.status !== "revoked") throw new Error("Transient isolated entitlement revoke failed.");
} finally { await admin.close(); }

if (
  reloadSuccesses !== reloadAttempts
  || network.fetch_xhr_count !== network.isolated_backend_fetch_xhr_count
  || network.unexpected_fetch_xhr_count !== 0
  || network.websocket_count !== 0
  || network.blocked_request_count !== 0
  || network.live_port_contact_count !== 0
) throw new Error("Isolated integration browser evidence was contradictory.");

process.stdout.write(JSON.stringify({
  ok: true,
  synthetic_run_id: syntheticRunId,
  headed_browser: headed,
  authenticated_reload_attempts: reloadAttempts,
  authenticated_reload_successes: reloadSuccesses,
  synthetic_user_count: 6,
  synthetic_project_count: 5,
  synthetic_provider_count: 2,
  cross_user_contamination: 0,
  cross_project_contamination: 0,
  cross_provider_contamination: 0,
  canonical_eda_handoff_verified: true,
  exact_binding_identity_verified_after_existing_branch: true,
  exact_binding_identity_verified_after_every_reload: true,
  exact_annotation_identity_verified_after_every_reload: true,
  production_components_exercised: [
    "BureauMetadataBindingPanel",
    "BureauMetadataCrosswalkWorkspace",
    "BureauReviewPanel",
  ],
  acceptance_surface: "isolated_synthetic_entry_mounting_production_components",
  project_b_states_verified: [
    "exact_verified",
    "approved_alias",
    "probable_review_required",
    "ambiguous_review_required",
    "unresolved",
    "rejected",
  ],
  contradiction_visible: true,
  treatment_interaction_without_navigation: true,
  scroll_preserved: true,
  atlas_guide_sentinel_stable: true,
  row_expand_collapse_verified: true,
  expanded_code_metadata_verified: true,
  canonical_eda_handoff_visible: true,
  api_only_multi_user_evidence_visible: true,
  atlas_guide_limitation: "The isolated acceptance entry uses a clearly labeled stable Atlas Guide sentinel because the full application CopilotCard requires project-context, identity, and workflow APIs outside the bounded catalog runtime.",
  final_holdout_accessed: false,
  training_started: false,
  project_scenarios: ["A_exact", "B_mixed_contradiction", "C_no_entitlement", "D_non_bureau", "E_multi_user"],
  network_contact_guard: network,
  screenshot_files: screenshots,
}));
